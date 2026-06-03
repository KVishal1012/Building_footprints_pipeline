from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from urllib.parse import quote_plus

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
    return PipelineConfig(
        **config_overrides,
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
    return run_pipeline(
        place_specs=place_specs,
        state_filters=state_filters,
        all_us_cities=all_us_cities,
        config=config,
    )


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
