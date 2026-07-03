from __future__ import annotations

import re
from dataclasses import dataclass
from types import ModuleType
from urllib.parse import quote_plus

from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS
from structures_pipeline.config import PipelineConfig
from structures_pipeline.pipeline import run_pipeline

US_SURVEY_FOOT_TO_METERS = 1200 / 3937
INTERNATIONAL_FOOT_TO_METERS = 0.3048
GEOGRAPHIC_METER_BUFFER_SRIDS = {4326, 4269}
FOOT_BASED_SRIDS = {
    2227,
    2230,
    2248,
    2263,
    2272,
    2276,
    3435,
    3436,
    3452,
    3453,
    6350,
    6420,
    6421,
}


@dataclass
class SqlServerPipelineSettings:
    """Collect SQL Server connection, baseline, buffer, and export settings."""

    server_name: str
    database_name: str
    output_table: str
    baseline_table: str
    baseline_buffer_value: float
    footprint_table: str | None = None
    footprint_raw_data_source: str | None = None
    footprint_geom_column: str = "Shape"
    footprint_srid: int | None = None
    footprint_optional: bool = False
    footprint_id_column: str | None = None
    footprint_structure_type_column: str | None = None
    footprint_units_column: str | None = None
    footprint_stories_column: str | None = None
    footprint_height_column: str | None = None
    footprint_occupant_count_column: str | None = None
    footprint_where: str | None = None
    footprint_structure_type_source: str | None = None
    footprint_units_source: str | None = None
    footprint_stories_source: str | None = None
    footprint_height_source: str | None = None
    footprint_occupant_count_source: str | None = None
    baseline_srid: int = 4326
    baseline_geom_column: str = "Shape"
    baseline_id_column: str | None = None
    baseline_where: str | None = None
    username: str | None = None
    password: str | None = None
    trusted_connection: bool = False
    driver: str = "ODBC Driver 18 for SQL Server"
    encrypt: str = "yes"
    trust_server_certificate: str | None = None
    output_if_exists: str = "append"
    output_geometry_column: str = "geometry_wkt"
    output_chunksize: int = 1000
    output_create_native_geometry: bool = False
    output_native_geometry_column: str = "Shape"
    output_native_geometry_srid: int = 4326
    preflight: bool = True
    buffer_unit_to_meters: float | None = None
    write_local_outputs: bool = False


# Convert a source-SRID buffer distance to meters for the pipeline buffer step.
def buffer_meters_from_srid(
    buffer_value: float,
    srid: int | None,
    *,
    unit_to_meters: float | None = None,
) -> float:
    """Convert a baseline buffer distance to meters using SRID unit context."""
    value = float(buffer_value)
    if value < 0:
        raise ValueError("Baseline buffer value must be zero or positive")
    if unit_to_meters is not None:
        if unit_to_meters <= 0:
            raise ValueError("buffer_unit_to_meters must be positive")
        return value * float(unit_to_meters)
    if srid in GEOGRAPHIC_METER_BUFFER_SRIDS:
        return value
    if srid in FOOT_BASED_SRIDS:
        return value * US_SURVEY_FOOT_TO_METERS
    return value


# Build a SQLAlchemy/pyodbc SQL Server URL from server and database settings.
def sql_server_connection_url(settings: SqlServerPipelineSettings) -> str:
    """Build a SQLAlchemy/pyodbc SQL Server URL from server and database settings."""
    parts = [
        f"Driver={{{settings.driver}}}",
        f"Server={settings.server_name}",
        f"Database={settings.database_name}",
        f"Encrypt={settings.encrypt}",
    ]
    if settings.trust_server_certificate is not None:
        parts.append(f"TrustServerCertificate={settings.trust_server_certificate}")
    if settings.trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        if not settings.username or settings.password is None:
            raise ValueError("SQL Server username and password are required unless trusted_connection=True")
        parts.extend([f"UID={settings.username}", f"PWD={settings.password}"])
    return "mssql+pyodbc:///?odbc_connect=" + quote_plus(";".join(parts))


# Split a schema-qualified SQL Server table name into schema and table parts.
def table_parts(table: str) -> tuple[str | None, str]:
    """Split a schema-qualified SQL Server table name into schema and table parts."""
    parts = [part.strip() for part in str(table).split(".") if part.strip()]
    if not parts or len(parts) > 2:
        raise ValueError("SQL Server table name must be table or schema.table")
    return (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])


# Return configured source columns that must exist on the footprint table.
def configured_footprint_columns(settings: SqlServerPipelineSettings) -> list[str]:
    """Return configured source columns that must exist on the footprint table."""
    columns = [
        settings.footprint_geom_column,
        settings.footprint_id_column,
        settings.footprint_structure_type_column,
        settings.footprint_units_column,
        settings.footprint_stories_column,
        settings.footprint_height_column,
        settings.footprint_occupant_count_column,
    ]
    return [column for column in columns if column]


def _sqlserver_quoted_name(name: str) -> str:
    """Validate and quote a dotted SQL Server identifier."""
    parts = [part.strip() for part in str(name).split(".") if part.strip()]
    if not parts:
        raise ValueError("SQL Server identifier cannot be empty")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_@$#]*", part) for part in parts):
        raise ValueError(f"Unsafe SQL Server identifier: {name}")
    return ".".join(f"[{part}]" for part in parts)


def _non_null_geometry_count_sql(table: str, geom_column: str, where: str | None = None) -> str:
    """Build a count query for rows with non-null SQL Server geometry."""
    predicate = f"{_sqlserver_quoted_name(geom_column)} IS NOT NULL"
    if where:
        predicate = f"({where}) AND {predicate}"
    return f"SELECT COUNT(*) AS row_count FROM {_sqlserver_quoted_name(table)} WHERE {predicate}"


def _scalar_int(conn, sql, text) -> int:
    """Execute a SQLAlchemy text query and return the first scalar integer."""
    result = conn.execute(text(sql))
    if hasattr(result, "scalar"):
        value = result.scalar()
    elif hasattr(result, "scalar_one"):
        value = result.scalar_one()
    else:
        row = result.fetchone()
        value = row[0] if row is not None else 0
    return int(value or 0)


def expected_sql_export_columns(settings: SqlServerPipelineSettings) -> list[str]:
    """Return the approved columns expected on an append-mode SQL export table."""
    columns = [column for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"]
    columns.append(settings.output_geometry_column)
    return columns


# Validate settings before an expensive pipeline/export run.
def validate_sql_server_settings(settings: SqlServerPipelineSettings) -> dict:
    """Validate settings before an expensive pipeline/export run."""
    if settings.output_if_exists not in {"append", "replace", "fail"}:
        raise ValueError("output_if_exists must be append, replace, or fail")
    if settings.output_chunksize <= 0:
        raise ValueError("output_chunksize must be positive")
    buffer_meters = buffer_meters_from_srid(
        settings.baseline_buffer_value,
        settings.baseline_srid,
        unit_to_meters=settings.buffer_unit_to_meters,
    )
    if settings.footprint_table:
        missing_sources = {
            "structure_type_source": (settings.footprint_structure_type_column, settings.footprint_structure_type_source),
            "units_source": (settings.footprint_units_column, settings.footprint_units_source),
            "stories_source": (settings.footprint_stories_column, settings.footprint_stories_source),
            "occupant_count_source": (settings.footprint_occupant_count_column, settings.footprint_occupant_count_source),
        }
        missing = [
            source_name
            for source_name, (value_column, source_label) in missing_sources.items()
            if value_column and not source_label
        ]
        if missing:
            raise ValueError(f"Footprint attribute columns require source labels: {missing}")
    return {
        "server_name": settings.server_name,
        "database_name": settings.database_name,
        "baseline_table": settings.baseline_table,
        "footprint_table": settings.footprint_table,
        "output_table": settings.output_table,
        "baseline_buffer_meters": buffer_meters,
        "output_if_exists": settings.output_if_exists,
        "footprint_optional": settings.footprint_optional,
        "create_native_geometry": settings.output_create_native_geometry,
    }


# Check SQL Server connectivity and configured table/column availability.
def preflight_sql_server_pipeline(settings: SqlServerPipelineSettings) -> dict:
    """Check SQL Server connectivity and configured table/column availability."""
    try:
        from sqlalchemy import create_engine, inspect, text
    except ImportError as exc:
        raise RuntimeError("sqlalchemy is required for SQL Server preflight") from exc

    summary = validate_sql_server_settings(settings)
    connection = sql_server_connection_url(settings)
    try:
        engine = create_engine(connection)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            inspector = inspect(engine)
            checks = []
            for table_name, required_columns in (
                (settings.baseline_table, [settings.baseline_geom_column, settings.baseline_id_column]),
                (settings.footprint_table, configured_footprint_columns(settings)),
            ):
                if not table_name:
                    continue
                schema, table = table_parts(table_name)
                exists = inspector.has_table(table, schema=schema)
                available_columns = []
                if exists:
                    available_columns = [column["name"] for column in inspector.get_columns(table, schema=schema)]
                missing_columns = [
                    column for column in required_columns if column and column not in available_columns
                ]
                checks.append(
                    {
                        "table": table_name,
                        "exists": bool(exists),
                        "required_columns": [column for column in required_columns if column],
                        "missing_columns": missing_columns,
                    }
                )
                if not exists:
                    raise RuntimeError(f"SQL Server preflight failed: table not found: {table_name}")
                if missing_columns:
                    raise RuntimeError(
                        f"SQL Server preflight failed: {table_name} is missing columns {missing_columns}"
                    )
                geom_column = (
                    settings.baseline_geom_column
                    if table_name == settings.baseline_table
                    else settings.footprint_geom_column
                )
                where = settings.baseline_where if table_name == settings.baseline_table else settings.footprint_where
                row_count = _scalar_int(conn, _non_null_geometry_count_sql(table_name, geom_column, where), text)
                checks[-1]["non_null_geometry_rows"] = row_count
                if table_name == settings.baseline_table and row_count == 0:
                    raise RuntimeError("SQL Server preflight failed: baseline table returned no non-null geometries")
                if table_name == settings.footprint_table and row_count == 0 and not settings.footprint_optional:
                    raise RuntimeError("SQL Server preflight failed: footprint table returned no non-null geometries")

            if settings.output_if_exists == "append":
                schema, table = table_parts(settings.output_table)
                if inspector.has_table(table, schema=schema):
                    available = [column["name"] for column in inspector.get_columns(table, schema=schema)]
                    missing_output_columns = [
                        column for column in expected_sql_export_columns(settings) if column not in available
                    ]
                    checks.append(
                        {
                            "table": settings.output_table,
                            "exists": True,
                            "required_columns": expected_sql_export_columns(settings),
                            "missing_columns": missing_output_columns,
                        }
                    )
                    if missing_output_columns:
                        raise RuntimeError(
                            "SQL Server preflight failed: append output table is missing columns "
                            f"{missing_output_columns}"
                        )
    except RuntimeError:
        raise
    except Exception as exc:
        message = str(exc)
        if "driver" in message.lower() or "odbc" in message.lower():
            raise RuntimeError(
                f"SQL Server preflight failed: ODBC driver or connection issue. "
                f"Check driver '{settings.driver}', server, credentials, and Encrypt settings. Details: {exc}"
            ) from exc
        raise RuntimeError(
            f"SQL Server preflight failed for {settings.server_name}/{settings.database_name}: {exc}"
        ) from exc
    summary["checks"] = checks
    summary["status"] = "passed"
    return summary


# Create a PipelineConfig with SQL Server baseline capture and final table export.
def build_sql_server_pipeline_config(
    settings: SqlServerPipelineSettings,
    **config_overrides,
) -> PipelineConfig:
    """Create a PipelineConfig with SQL Server baseline capture and final table export."""
    connection = sql_server_connection_url(settings)
    buffer_meters = buffer_meters_from_srid(
        settings.baseline_buffer_value,
        settings.baseline_srid,
        unit_to_meters=settings.buffer_unit_to_meters,
    )
    footprint_source = None
    if settings.footprint_table:
        footprint_source = {
            "connection": connection,
            "table": settings.footprint_table,
            "raw_data_source": settings.footprint_raw_data_source or settings.footprint_table,
            "load_source": "sql_server",
            "geom_column": settings.footprint_geom_column,
            "id_column": settings.footprint_id_column,
            "structure_type_column": settings.footprint_structure_type_column,
            "units_column": settings.footprint_units_column,
            "stories_column": settings.footprint_stories_column,
            "height_column": settings.footprint_height_column,
            "occupant_count_column": settings.footprint_occupant_count_column,
            "where": settings.footprint_where,
            "structure_type_source": settings.footprint_structure_type_source,
            "units_source": settings.footprint_units_source,
            "stories_source": settings.footprint_stories_source,
            "height_source": settings.footprint_height_source,
            "occupant_count_source": settings.footprint_occupant_count_source,
            "crs": f"EPSG:{int(settings.footprint_srid or settings.baseline_srid)}",
            "srid": int(settings.footprint_srid or settings.baseline_srid),
            "source_name": settings.footprint_raw_data_source or settings.footprint_table,
            "sqlserver_geometry_methods": True,
        }
    return PipelineConfig(
        **config_overrides,
        sql_footprint_source=footprint_source,
        sql_baseline_source={
            "connection": connection,
            "table": settings.baseline_table,
            "geom_column": settings.baseline_geom_column,
            "id_column": settings.baseline_id_column,
            "where": settings.baseline_where,
            "crs": f"EPSG:{settings.baseline_srid}",
            "buffer_meters": buffer_meters,
            "sqlserver_geometry_methods": True,
        },
        sql_export={
            "connection": connection,
            "table": settings.output_table,
            "if_exists": settings.output_if_exists,
            "geometry_column": settings.output_geometry_column,
            "chunksize": settings.output_chunksize,
            "use_explicit_schema": True,
            "create_native_geometry": settings.output_create_native_geometry,
            "native_geometry_column": settings.output_native_geometry_column,
            "native_geometry_srid": settings.output_native_geometry_srid,
        },
        return_dataframe=True,
        write_local_outputs=settings.write_local_outputs,
    )


# Run the pipeline with SQL Server baseline/export settings and return the result dict.
def run_sql_server_pipeline(
    settings: SqlServerPipelineSettings,
    *,
    place_specs: list[dict[str, str]] | None = None,
    state_filters: list[str] | None = None,
    all_us_cities: bool = False,
    **config_overrides,
) -> dict:
    """Run the pipeline with SQL Server baseline/export settings and return the result dict."""
    config = build_sql_server_pipeline_config(settings, **config_overrides)
    preflight_result = preflight_sql_server_pipeline(settings) if settings.preflight else None
    if preflight_result is not None:
        preflight_result["derive_num_units"] = bool(config.derive_num_units)
        preflight_result["derive_occupant_count"] = bool(config.derive_occupant_count)
    result = run_pipeline(
        place_specs=place_specs,
        state_filters=state_filters,
        all_us_cities=all_us_cities,
        config=config,
    )
    result["preflight"] = preflight_result
    if config.sql_export and not result.get("sql_export"):
        raise RuntimeError("SQL Server export was configured but no export result was produced")
    return result


# Run from a Python input module with get_settings/get_target/get_pipeline_overrides.
def run_sql_server_pipeline_from_inputs(input_module: ModuleType) -> dict:
    """Run from a Python input module with get_settings/get_target/get_pipeline_overrides."""
    for function_name in ("get_settings", "get_target", "get_pipeline_overrides"):
        if not hasattr(input_module, function_name):
            raise ValueError(f"Input module is missing required function: {function_name}")
    settings = input_module.get_settings()
    target = dict(input_module.get_target())
    overrides = dict(input_module.get_pipeline_overrides())
    return run_sql_server_pipeline(
        settings,
        place_specs=target.get("place_specs"),
        state_filters=target.get("state_filters"),
        all_us_cities=bool(target.get("all_us_cities", False)),
        **overrides,
    )
