from __future__ import annotations

import gzip
import json
import os
import logging
import math
import re
import ssl
from pathlib import Path
from urllib.request import urlopen

import certifi
import geopandas as gpd
import mercantile
import numpy as np
import pandas as pd
import requests
from shapely import wkb, wkt
from shapely.geometry import box, shape

from structures_pipeline.config import PipelineConfig
from structures_pipeline.constants import (
    CENSUS_ACS_URL,
    MICROSOFT_DATASET_LINKS_URL,
    NSI_STRUCTURES_URL,
    OVERTURE_AZURE_BUILDINGS_GLOB,
    OVERTURE_STAC_URL,
    PARCEL_FIELD_ALIASES,
    PARCEL_TEXT_COLUMNS,
    REQUIRED_OUTPUT_COLUMNS,
)
from structures_pipeline.geometry import (
    assign_footprints_to_place,
    bounds_tuple,
    clean_geom,
    dedupe_fallback_footprints,
    empty_gdf,
    estimated_projected_crs,
    normalize_boundary,
)
from structures_pipeline.utils import ensure_columns, parse_height_meters, slugify, to_numeric_safe

LOGGER = logging.getLogger(__name__)


# Read GeoParquet, falling back to WKB decoding for plain parquet geometry.
def read_wkb_parquet(path: Path, crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    """Read GeoParquet, falling back to WKB decoding for plain parquet geometry."""
    try:
        gdf = gpd.read_parquet(path)
        if isinstance(gdf, gpd.GeoDataFrame) and gdf.geometry.name in gdf.columns:
            return gdf if gdf.crs else gdf.set_crs(crs)
    except Exception:
        pass

    df = pd.read_parquet(path)
    if "geometry" not in df.columns:
        return empty_gdf(df.columns, crs=crs)
    geometry = gpd.GeoSeries.from_wkb(df.pop("geometry"), crs=crs)
    return gpd.GeoDataFrame(df, geometry=geometry, crs=crs)


# Resolve the configured or latest available Overture release identifier.
def resolve_overture_release(config: PipelineConfig) -> str | None:
    """Resolve the configured or latest available Overture release identifier."""
    if config.source_version and config.source_version != "latest":
        return config.source_version
    if not config.download_missing:
        return "latest"
    try:
        response = requests.get(OVERTURE_STAC_URL, timeout=config.request_timeout_sec)
        response.raise_for_status()
        latest = response.json().get("latest")
        if latest:
            return str(latest)
    except Exception as exc:
        LOGGER.warning("Could not resolve latest Overture release: %s", exc)
    return None


# Escape single quotes for DuckDB SQL string interpolation.
def _sql_quote(value: str | Path) -> str:
    """Escape single quotes for DuckDB SQL string interpolation."""
    return str(value).replace("'", "''")


# Decode WKB, hex WKB, WKT, or shapely-like geometry values from SQL rows.
def _decode_sql_geometry(value):
    """Decode WKB, hex WKB, WKT, or shapely-like geometry values from SQL rows."""
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytearray):
        value = bytes(value)
    if isinstance(value, bytes):
        return wkb.loads(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return wkb.loads(bytes.fromhex(stripped))
        except Exception:
            return wkt.loads(stripped)
    if hasattr(value, "wkb"):
        return value
    return value


# Load a SQL table/query into a GeoDataFrame using a configured geometry column.
def read_sql_geometry_source(source: dict, config: PipelineConfig) -> gpd.GeoDataFrame:
    """Load a SQL table/query into a GeoDataFrame using a configured geometry column."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise RuntimeError("sqlalchemy is required for SQL geometry sources") from exc

    connection = source.get("connection")
    connection_env = source.get("connection_env") or "STRUCTURES_SQL_URL"
    if not connection:
        connection = os.environ.get(connection_env)
    if not connection:
        raise RuntimeError(f"Missing SQL connection string. Set {connection_env} or pass connection in config.")

    table = source.get("table")
    query = source.get("query")
    if table and query:
        raise ValueError("SQL source can use table or query, not both")
    use_sqlserver_methods = bool(source.get("sqlserver_geometry_methods"))
    if query:
        sql = str(query)
    elif table and use_sqlserver_methods:
        sql = _sqlserver_geometry_select(source)
    elif table:
        columns = list(source.get("columns") or [])
        if not columns and any(
            source.get(key)
            for key in (
                "id_column",
                "structure_type_column",
                "units_column",
                "height_column",
                "stories_column",
                "occupant_count_column",
            )
        ):
            columns = [source.get("geom_column", "geom")]
        for key in (
            "id_column",
            "structure_type_column",
            "units_column",
            "height_column",
            "stories_column",
            "occupant_count_column",
        ):
            column = source.get(key)
            if column and column not in columns:
                columns.append(column)
        sql = f"SELECT {', '.join(columns)} FROM {table}" if columns else f"SELECT * FROM {table}"
        where = source.get("where")
        if where:
            sql = f"{sql} WHERE {where}"
    else:
        raise ValueError("SQL source requires table or query")

    engine = create_engine(connection)
    with engine.connect() as conn:
        df = pd.read_sql_query(text(sql), conn)
    geom_column = source.get("geom_column", "geom")
    if use_sqlserver_methods and not query:
        geom_column = "geometry_wkb"
    if geom_column not in df.columns:
        raise ValueError(f"SQL source is missing geometry column: {geom_column}")
    geometry = df.pop(geom_column).map(_decode_sql_geometry)
    crs = source.get("crs", "EPSG:4326")
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)
    if "geometry_srid" in gdf.columns:
        srid = pd.to_numeric(gdf.pop("geometry_srid"), errors="coerce").dropna()
        if not srid.empty and srid.iloc[0]:
            gdf = gdf.set_crs(f"EPSG:{int(srid.iloc[0])}", allow_override=True)
    return gdf


# Validate and quote a dotted SQL Server identifier such as schema.table.
def _sqlserver_name(name: str) -> str:
    """Validate and quote a dotted SQL Server identifier such as schema.table."""
    parts = [part.strip() for part in name.split(".") if part.strip()]
    if not parts:
        raise ValueError("SQL Server identifier cannot be empty")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_@$#]*", part) for part in parts):
        raise ValueError(f"Unsafe SQL Server identifier: {name}")
    return ".".join(f"[{part}]" for part in parts)


# Build a SQL Server SELECT that converts geometry/geography columns to WKB.
def _sqlserver_geometry_select(source: dict) -> str:
    """Build a SQL Server SELECT that converts geometry/geography columns to WKB."""
    table = source.get("table")
    if not table:
        raise ValueError("SQL Server geometry source requires table")
    geom_column = source.get("geom_column", "geom")
    select_parts = [
        f"{_sqlserver_name(geom_column)}.STAsBinary() AS geometry_wkb",
        f"{_sqlserver_name(geom_column)}.STSrid AS geometry_srid",
    ]
    for column in source.get("columns") or []:
        if column != geom_column:
            select_parts.append(f"{_sqlserver_name(column)} AS {_sqlserver_name(column)}")
    for key in (
        "id_column",
        "structure_type_column",
        "units_column",
        "height_column",
        "stories_column",
        "occupant_count_column",
    ):
        column = source.get(key)
        if column and column != geom_column and column not in (source.get("columns") or []):
            select_parts.append(f"{_sqlserver_name(column)} AS {_sqlserver_name(column)}")
    where = f" WHERE {source.get('where')}" if source.get("where") else ""
    return f"SELECT {', '.join(select_parts)} FROM {_sqlserver_name(table)}{where}"


# Split an optional schema-qualified table name for pandas to_sql.
def _sql_table_parts(table: str) -> tuple[str | None, str]:
    """Split an optional schema-qualified table name for pandas to_sql."""
    parts = [part.strip() for part in table.split(".") if part.strip()]
    if not parts or len(parts) > 2:
        raise ValueError("SQL export table must be table or schema.table")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_@$#]*", part) for part in parts):
        raise ValueError(f"Unsafe SQL export table identifier: {table}")
    return (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])


# Return the approved structure columns that are present and safe for SQL export.
def approved_sql_export_columns(gdf: gpd.GeoDataFrame, geometry_column: str) -> list[str]:
    """Return the approved structure columns that are present and safe for SQL export."""
    approved_without_geometry = [column for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"]
    columns = [column for column in approved_without_geometry if column in gdf.columns]
    columns.append(geometry_column)
    return columns


# Convert a GeoDataFrame into approved rows that can be inserted by pandas/SQLAlchemy.
def dataframe_for_sql_export(
    gdf: gpd.GeoDataFrame,
    geometry_column: str = "geometry_wkt",
) -> pd.DataFrame:
    """Convert a GeoDataFrame into approved rows that can be inserted by pandas/SQLAlchemy."""
    approved_without_geometry = [column for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"]
    available_columns = [column for column in approved_without_geometry if column in gdf.columns]
    frame = pd.DataFrame(gdf[available_columns]).copy()
    geometry = gdf.geometry
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        geometry = gdf.to_crs(epsg=4326).geometry
    frame[geometry_column] = geometry.to_wkt()
    return frame


# Build a compact export QA report for SQL-only runs.
def sql_export_quality_report(frame: pd.DataFrame, *, source_columns: list[str] | None = None) -> dict:
    """Build a compact export QA report for SQL-only runs."""
    critical_columns = [
        "StructureID",
        "StructureType",
        "NumStories",
        "NumUnits",
        "OccupantCount",
        "StructureTypeSource",
        "NumStoriesSource",
        "NumUnitsSource",
        "OccupantCountSource",
    ]
    null_counts = {
        column: int(frame[column].isna().sum())
        for column in critical_columns
        if column in frame.columns
    }
    datasource_columns = [
        "StructureTypeSource",
        "NumStoriesSource",
        "NumUnitsSource",
        "OccupantCountSource",
    ]
    datasource_completeness = {
        column: float(frame[column].notna().mean()) if len(frame) else 0.0
        for column in datasource_columns
        if column in frame.columns
    }
    report = {
        "row_count": int(len(frame)),
        "exported_columns": list(frame.columns),
        "unexpected_columns_dropped": sorted(set(source_columns or []) - set(frame.columns)),
        "null_counts": null_counts,
        "datasource_completeness": datasource_completeness,
    }
    allowed_columns = set(REQUIRED_OUTPUT_COLUMNS) - {"geometry"}
    allowed_columns.add("geometry_wkt")
    report["source_had_unapproved_columns"] = bool(report["unexpected_columns_dropped"])
    report["approved_output_contract"] = set(frame.columns).issubset(allowed_columns)
    return report


# Return explicit SQLAlchemy dtypes for important SQL Server export columns.
def sql_export_dtype_map(frame: pd.DataFrame) -> dict:
    """Return explicit SQLAlchemy dtypes for important SQL Server export columns."""
    try:
        from sqlalchemy import DateTime, Float, Integer, Unicode, UnicodeText
    except ImportError as exc:
        raise RuntimeError("sqlalchemy is required for SQL export dtype mapping") from exc
    text_255 = Unicode(255)
    dtype = {}
    for column in frame.columns:
        lower = str(column).lower()
        if lower in {"geometry_wkt", "change_log"} or lower.endswith("source"):
            dtype[column] = UnicodeText()
        elif lower.endswith("confidence") or lower.endswith("_m") or lower.endswith("_sqft") or lower in {
            "numunits",
            "numstories",
            "occupantcount",
        }:
            dtype[column] = Float()
        elif lower in {"censusyear"}:
            dtype[column] = Integer()
        elif lower.endswith("at") or "timestamp" in lower:
            dtype[column] = DateTime()
        elif frame[column].dtype == object or str(frame[column].dtype).startswith("string"):
            dtype[column] = text_255
    return dtype


# Raise when populated attributes lack the datasource columns required for source-of-truth export.
def validate_attribute_datasources(frame: pd.DataFrame) -> None:
    """Raise when populated attributes lack the datasource columns required for source-of-truth export."""
    checks = {
        "StructureType": "StructureTypeSource",
        "NumStories": "NumStoriesSource",
        "NumUnits": "NumUnitsSource",
        "OccupantCount": "OccupantCountSource",
    }
    for value_column, source_column in checks.items():
        if value_column not in frame.columns or source_column not in frame.columns:
            continue
        has_value = frame[value_column].notna() & frame[value_column].astype(str).str.strip().ne("")
        missing_source = frame[source_column].isna() | frame[source_column].astype(str).str.strip().eq("")
        if (has_value & missing_source).any():
            raise ValueError(f"SQL export blocked: {value_column} values require {source_column}")


# Export the final structure dataframe to a SQL Server-compatible table.
def export_dataframe_to_sql_server(
    gdf: gpd.GeoDataFrame,
    export_config: dict,
) -> dict:
    """Export the final structure dataframe to a SQL Server-compatible table."""
    try:
        from sqlalchemy import create_engine
    except ImportError as exc:
        raise RuntimeError("sqlalchemy is required for SQL Server export") from exc

    table = export_config.get("table")
    if not table:
        raise ValueError("SQL Server export requires table")
    connection = export_config.get("connection")
    connection_env = export_config.get("connection_env") or "STRUCTURES_SQLSERVER_URL"
    if not connection:
        connection = os.environ.get(connection_env)
    if not connection:
        raise RuntimeError(
            f"Missing SQL Server export connection string. Set {connection_env} or pass connection in config."
        )

    schema, table_name = _sql_table_parts(table)
    geometry_column = export_config.get("geometry_column") or "geometry_wkt"
    frame = dataframe_for_sql_export(gdf, geometry_column=geometry_column)
    validate_attribute_datasources(frame)
    source_columns = [
        column
        for column in gdf.columns
        if column != gdf.geometry.name
    ] + [geometry_column]
    quality_report = sql_export_quality_report(frame, source_columns=source_columns)
    engine_kwargs = {}
    if str(connection).lower().startswith("mssql") and export_config.get("fast_executemany", True):
        engine_kwargs["fast_executemany"] = True
    try:
        engine = create_engine(connection, **engine_kwargs)
        dtype = sql_export_dtype_map(frame) if export_config.get("use_explicit_schema", True) else None
        frame.to_sql(
            table_name,
            engine,
            schema=schema,
            if_exists=export_config.get("if_exists", "fail"),
            index=False,
            chunksize=int(export_config.get("chunksize") or 1000),
            dtype=dtype,
        )
    except Exception as exc:
        message = str(exc)
        if "driver" in message.lower() or "odbc" in message.lower():
            raise RuntimeError(
                "SQL Server export failed: check the ODBC driver, connection string, credentials, and Encrypt settings. "
                f"Details: {exc}"
            ) from exc
        raise RuntimeError(f"SQL Server export failed for table {table}: {exc}") from exc
    return {
        "table": table,
        "rows_exported": int(len(frame)),
        "geometry_column": geometry_column,
        "if_exists": export_config.get("if_exists", "fail"),
        "quality_report": quality_report,
    }


# Read baseline geometries and keep only BaselineID plus geometry.
def read_sql_baseline_source(source: dict, config: PipelineConfig) -> gpd.GeoDataFrame:
    """Read baseline geometries and keep only BaselineID plus geometry."""
    table = source.get("table")
    query = source.get("query")
    geom_column = source.get("geom_column", "geom")
    use_sqlserver_methods = bool(source.get("sqlserver_geometry_methods"))
    if table and not query and use_sqlserver_methods:
        baseline_source = dict(source)
        if source.get("id_column"):
            baseline_source["columns"] = [source["id_column"]]
        baseline_source["query"] = _sqlserver_geometry_select(baseline_source)
        if source.get("id_column"):
            baseline_source["query"] = baseline_source["query"].replace(
                f" AS {_sqlserver_name(source['id_column'])}",
                " AS BaselineID",
            )
        baseline_source.pop("table", None)
        baseline_source["geom_column"] = "geometry_wkb"
        raw = read_sql_geometry_source(baseline_source, config)
    else:
        raw = read_sql_geometry_source(source, config)

    if raw.empty:
        return empty_gdf(["BaselineID"])
    baseline = raw.to_crs(epsg=4326).reset_index(drop=True)
    id_column = source.get("id_column")
    if "BaselineID" not in baseline.columns:
        if id_column and id_column in baseline.columns:
            baseline["BaselineID"] = baseline[id_column].astype(str)
        else:
            baseline["BaselineID"] = [f"baseline_{i}" for i in range(len(baseline))]
    return baseline[["BaselineID", "geometry"]]


# Buffer baseline features in meters and union them into an EPSG:4326 AOI.
def buffered_baseline_boundary(baseline: gpd.GeoDataFrame, buffer_meters: float) -> gpd.GeoDataFrame:
    """Buffer baseline features in meters and union them into an EPSG:4326 AOI."""
    if baseline.empty:
        raise ValueError("SQL baseline returned no geometries")
    work_crs = estimated_projected_crs(baseline)
    buffered = baseline.to_crs(work_crs).geometry.buffer(buffer_meters)
    unioned = buffered.union_all() if hasattr(buffered, "union_all") else buffered.unary_union
    boundary = gpd.GeoDataFrame(geometry=[unioned], crs=work_crs).to_crs(epsg=4326)
    return normalize_boundary(boundary)


# Attach nearest baseline ID, distance, and buffer distance to each structure.
def attach_baseline_proximity(
    structures: gpd.GeoDataFrame,
    baseline: gpd.GeoDataFrame,
    buffer_meters: float,
) -> gpd.GeoDataFrame:
    """Attach nearest baseline ID, distance, and buffer distance to each structure."""
    if structures.empty or baseline.empty:
        return structures
    work_crs = estimated_projected_crs(structures, baseline)
    points = structures[["StructureID", "geometry"]].copy().to_crs(work_crs)
    points["geometry"] = points.geometry.representative_point()
    baseline_work = baseline[["BaselineID", "geometry"]].copy().to_crs(work_crs)
    nearest = gpd.sjoin_nearest(
        points,
        baseline_work,
        how="left",
        distance_col="BaselineDistance_m",
    ).drop_duplicates("StructureID")
    nearest = nearest.set_index("StructureID")

    out = structures.set_index("StructureID")
    out["BaselineID"] = nearest["BaselineID"].reindex(out.index)
    out["BaselineDistance_m"] = nearest["BaselineDistance_m"].reindex(out.index)
    out["BaselineBuffer_m"] = buffer_meters
    return out.reset_index()


# Normalize SQL footprint rows to the shared raw footprint schema.
def standardize_sql_footprints(gdf: gpd.GeoDataFrame, place: pd.Series, source: dict) -> gpd.GeoDataFrame:
    """Normalize SQL footprint rows to the shared raw footprint schema."""
    if gdf.empty:
        return empty_gdf()
    gdf = clean_geom(gdf.to_crs(epsg=4326)).reset_index(drop=True)
    city_slug = slugify(place["City"], place["State"], "USA")
    id_column = source.get("id_column")
    if id_column and id_column in gdf.columns:
        source_ids = gdf[id_column].astype(str)
    else:
        source_ids = pd.Series(gdf.index, index=gdf.index).astype(str)
    source_name = source.get("source_name") or "sql"
    raw_data_source = source.get("raw_data_source") or source_name
    load_source = source.get("load_source") or "sql_server"
    structure_type_column = source.get("structure_type_column")
    units_column = source.get("units_column")
    height_column = source.get("height_column")
    stories_column = source.get("stories_column")
    occupant_count_column = source.get("occupant_count_column")
    structure_type_source = source.get("structure_type_source") or (
        f"{raw_data_source}_{structure_type_column}" if structure_type_column else pd.NA
    )
    units_source = source.get("units_source") or (
        f"{raw_data_source}_{units_column}" if units_column else pd.NA
    )
    stories_source = source.get("stories_source") or (
        f"{raw_data_source}_{stories_column}" if stories_column else pd.NA
    )
    height_source = source.get("height_source") or (
        f"{raw_data_source}_{height_column}" if height_column else pd.NA
    )
    occupant_count_source = source.get("occupant_count_source") or (
        f"{raw_data_source}_{occupant_count_column}" if occupant_count_column else pd.NA
    )
    out = gpd.GeoDataFrame(
        {
            "StructureID": f"sql_{place['PlaceGEOID']}_{city_slug}_" + source_ids,
            "LoadSource": load_source,
            "RawDataSource": raw_data_source,
            "FootprintSource": raw_data_source,
            "OvertureID": pd.Series(pd.NA, index=gdf.index, dtype="string"),
            "MicrosoftID": pd.Series(pd.NA, index=gdf.index, dtype="string"),
            "BuildingName_OVT": pd.Series(pd.NA, index=gdf.index),
            "Height_OVT": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "Stories_OVT": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "OvertureSubtype": pd.Series(pd.NA, index=gdf.index),
            "OvertureClass": pd.Series(pd.NA, index=gdf.index),
            "SQLStructureType": gdf[structure_type_column] if structure_type_column in gdf.columns else pd.Series(pd.NA, index=gdf.index),
            "SQLStructureTypeSource": pd.Series(structure_type_source, index=gdf.index),
            "SQLUnits": to_numeric_safe(gdf[units_column], index=gdf.index) if units_column in gdf.columns else pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "SQLUnitsSource": pd.Series(units_source, index=gdf.index),
            "SQLHeight": to_numeric_safe(gdf[height_column], index=gdf.index) if height_column in gdf.columns else pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "SQLHeightSource": pd.Series(height_source, index=gdf.index),
            "SQLStories": to_numeric_safe(gdf[stories_column], index=gdf.index) if stories_column in gdf.columns else pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "SQLStoriesSource": pd.Series(stories_source, index=gdf.index),
            "SQLOccupantCount": to_numeric_safe(gdf[occupant_count_column], index=gdf.index) if occupant_count_column in gdf.columns else pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "SQLOccupantCountSource": pd.Series(occupant_count_source, index=gdf.index),
            "HasParts": pd.Series(pd.NA, index=gdf.index),
            "Height_MS": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "Confidence_MS": pd.Series(np.nan, index=gdf.index, dtype="float64"),
        },
        geometry=gdf.geometry,
        crs="EPSG:4326",
    )
    return out.reset_index(drop=True)


# Load configured SQL footprints and spatially assign them to a place boundary.
def load_sql_footprints(
    place: pd.Series,
    boundary: gpd.GeoDataFrame,
    config: PipelineConfig,
) -> gpd.GeoDataFrame:
    """Load configured SQL footprints and spatially assign them to a place boundary."""
    source = config.sql_footprint_source
    if not config.use_sql or not source:
        return empty_gdf()
    try:
        raw = read_sql_geometry_source(source, config)
    except Exception as exc:
        LOGGER.warning("SQL footprint source skipped for %s: %s", place["PlaceGEOID"], exc)
        return empty_gdf()
    standardized = standardize_sql_footprints(raw, place, source)
    return assign_footprints_to_place(standardized, boundary).reset_index(drop=True)


# Stream Overture building rows inside an AOI bbox directly to GeoParquet.
def download_overture_with_duckdb(
    boundary: gpd.GeoDataFrame,
    output_path: Path,
    release: str,
) -> None:
    """Stream Overture building rows inside an AOI bbox directly to GeoParquet."""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("duckdb is required for remote Overture querying") from exc

    minx, miny, maxx, maxy = bounds_tuple(boundary)
    glob = OVERTURE_AZURE_BUILDINGS_GLOB.format(release=release)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
        sql = f"""
            COPY (
                SELECT
                    id AS OvertureID,
                    names.primary AS BuildingName_OVT,
                    TRY_CAST(height AS DOUBLE) AS Height_OVT,
                    TRY_CAST(num_floors AS DOUBLE) AS Stories_OVT,
                    subtype AS OvertureSubtype,
                    class AS OvertureClass,
                    has_parts AS HasParts,
                    geometry
                FROM read_parquet('{_sql_quote(glob)}', hive_partitioning = 1)
                WHERE bbox.xmin <= {maxx}
                  AND bbox.xmax >= {minx}
                  AND bbox.ymin <= {maxy}
                  AND bbox.ymax >= {miny}
            )
            TO '{_sql_quote(output_path)}' (FORMAT PARQUET)
        """
        con.execute(sql)
    finally:
        con.close()


# Load cached or downloaded Overture buildings and assign them to the place.
def load_overture_buildings(
    place: pd.Series,
    boundary: gpd.GeoDataFrame,
    config: PipelineConfig,
    release: str | None,
) -> gpd.GeoDataFrame:
    """Load cached or downloaded Overture buildings and assign them to the place."""
    if not config.use_overture:
        return empty_gdf()
    city_slug = slugify(place["City"], place["State"], "USA")
    raw_path = config.raw_dir / f"overture_{place['PlaceGEOID']}_{city_slug}.parquet"
    if (not raw_path.exists() or config.overwrite_raw) and config.download_missing:
        if not release or release == "latest":
            LOGGER.warning("Overture skipped: latest release could not be resolved")
        else:
            try:
                LOGGER.info("Querying Overture %s for %s", release, city_slug)
                download_overture_with_duckdb(boundary, raw_path, release)
            except Exception as exc:
                LOGGER.warning("Overture source skipped for %s: %s", city_slug, exc)
    if not raw_path.exists():
        LOGGER.info("Overture source skipped for %s: no cached file", city_slug)
        return empty_gdf()

    raw = read_wkb_parquet(raw_path)
    if raw.empty:
        return empty_gdf()
    raw = clean_geom(raw.to_crs(epsg=4326)).reset_index(drop=True)
    out = gpd.GeoDataFrame(
        {
            "StructureID": "ovt_" + raw.get("OvertureID", pd.Series(raw.index)).astype(str),
            "FootprintSource": "overture",
            "OvertureID": raw.get("OvertureID", pd.Series(pd.NA, index=raw.index)).astype("string"),
            "MicrosoftID": pd.Series(pd.NA, index=raw.index, dtype="string"),
            "BuildingName_OVT": raw.get("BuildingName_OVT", pd.Series(pd.NA, index=raw.index)),
            "Height_OVT": to_numeric_safe(raw.get("Height_OVT"), index=raw.index),
            "Stories_OVT": to_numeric_safe(raw.get("Stories_OVT"), index=raw.index),
            "OvertureSubtype": raw.get("OvertureSubtype", pd.Series(pd.NA, index=raw.index)),
            "OvertureClass": raw.get("OvertureClass", pd.Series(pd.NA, index=raw.index)),
            "HasParts": raw.get("HasParts", pd.Series(pd.NA, index=raw.index)),
            "Height_MS": pd.Series(np.nan, index=raw.index, dtype="float64"),
            "Confidence_MS": pd.Series(np.nan, index=raw.index, dtype="float64"),
        },
        geometry=raw.geometry,
        crs="EPSG:4326",
    )
    return assign_footprints_to_place(out, boundary).reset_index(drop=True)


# Read a remote CSV with the certifi CA bundle for SSL consistency.
def read_remote_csv(url: str, **kwargs) -> pd.DataFrame:
    """Read a remote CSV with the certifi CA bundle for SSL consistency."""
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(url, context=ssl_context) as response:
        return pd.read_csv(response, **kwargs)


# Read plain or gzipped remote JSON-lines data into a DataFrame.
def read_remote_json_lines(url: str) -> pd.DataFrame:
    """Read plain or gzipped remote JSON-lines data into a DataFrame."""
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(url, context=ssl_context) as response:
        if url.split("?", 1)[0].endswith(".gz"):
            with gzip.GzipFile(fileobj=response) as decompressed:
                return pd.read_json(decompressed, lines=True)
        return pd.read_json(response, lines=True)


# Return Microsoft tile quadkeys intersecting a lon/lat bounding box.
def quadkeys_for_bounds(bounds: tuple[float, float, float, float], zoom: int) -> list[str]:
    """Return Microsoft tile quadkeys intersecting a lon/lat bounding box."""
    minx, miny, maxx, maxy = bounds
    return sorted(
        {mercantile.quadkey(tile) for tile in mercantile.tiles(minx, miny, maxx, maxy, zooms=[zoom])}
    )


# Read one Microsoft footprint tile and keep only useful geometry attributes.
def read_microsoft_tile(url: str) -> gpd.GeoDataFrame:
    """Read one Microsoft footprint tile and keep only useful geometry attributes."""
    df = read_remote_json_lines(url)
    if "properties" in df.columns:
        properties = pd.json_normalize(df["properties"]).set_index(df.index)
        df = pd.concat([df.drop(columns=["properties"]), properties], axis=1)
    df["geometry"] = df["geometry"].apply(
        lambda geometry: shape(geometry) if isinstance(geometry, dict) else geometry
    )
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    keep = [column for column in ["height", "confidence", "geometry"] if column in gdf]
    return gdf[keep]


# Download Microsoft tiles for an AOI, prefiltering links to avoid repeated scans.
def download_microsoft_buildings(
    boundary: gpd.GeoDataFrame,
    output_path: Path,
    config: PipelineConfig,
) -> gpd.GeoDataFrame:
    """Download Microsoft tiles for an AOI, prefiltering links to avoid repeated scans."""
    bounds = bounds_tuple(boundary)
    quad_keys = quadkeys_for_bounds(bounds, zoom=config.microsoft_zoom)
    links = read_remote_csv(MICROSOFT_DATASET_LINKS_URL, dtype=str)
    links = links[links["QuadKey"].isin(set(quad_keys))]
    pieces: list[gpd.GeoDataFrame] = []
    minx, miny, maxx, maxy = bounds

    for url in links["Url"].dropna().unique():
        tile = read_microsoft_tile(url)
        if tile.empty:
            continue
        tile = tile.cx[minx:maxx, miny:maxy]
        if not tile.empty:
            pieces.append(tile)

    if not pieces:
        return empty_gdf()
    microsoft = gpd.GeoDataFrame(
        pd.concat(pieces, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )
    microsoft = clean_geom(microsoft)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    microsoft.to_parquet(output_path, index=False)
    return microsoft


# Normalize Microsoft fallback footprints to the shared footprint schema.
def standardize_microsoft(gdf: gpd.GeoDataFrame, place: pd.Series) -> gpd.GeoDataFrame:
    """Normalize Microsoft fallback footprints to the shared footprint schema."""
    if gdf.empty:
        return empty_gdf()
    gdf = clean_geom(gdf.to_crs(epsg=4326)).reset_index(drop=True)
    city_slug = slugify(place["City"], place["State"], "USA")
    index = pd.Series(gdf.index, index=gdf.index).astype(str)
    out = gpd.GeoDataFrame(
        {
            "StructureID": f"msft_{place['PlaceGEOID']}_{city_slug}_" + index,
            "FootprintSource": "microsoft_fallback",
            "OvertureID": pd.Series(pd.NA, index=gdf.index, dtype="string"),
            "MicrosoftID": f"msft_{place['PlaceGEOID']}_{city_slug}_" + index,
            "BuildingName_OVT": pd.Series(pd.NA, index=gdf.index),
            "Height_OVT": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "Stories_OVT": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "OvertureSubtype": pd.Series(pd.NA, index=gdf.index),
            "OvertureClass": pd.Series(pd.NA, index=gdf.index),
            "HasParts": pd.Series(False, index=gdf.index),
            "Height_MS": to_numeric_safe(gdf.get("height"), index=gdf.index).replace(-1, np.nan),
            "Confidence_MS": to_numeric_safe(gdf.get("confidence"), index=gdf.index).replace(-1, np.nan),
        },
        geometry=gdf.geometry,
        crs="EPSG:4326",
    )
    return out.reset_index(drop=True)


# Load Microsoft fallback footprints and remove rows duplicated by primary data.
def load_microsoft_fallback(
    place: pd.Series,
    boundary: gpd.GeoDataFrame,
    config: PipelineConfig,
    primary: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Load Microsoft fallback footprints and remove rows duplicated by primary data."""
    if not config.use_microsoft or not config.add_microsoft_fallback:
        return empty_gdf()
    city_slug = slugify(place["City"], place["State"], "USA")
    raw_path = config.raw_dir / f"microsoft_{place['PlaceGEOID']}_{city_slug}.parquet"
    if raw_path.exists() and not config.overwrite_raw:
        raw = gpd.read_parquet(raw_path)
    elif config.download_missing:
        try:
            raw = download_microsoft_buildings(boundary, raw_path, config)
        except Exception as exc:
            LOGGER.warning("Microsoft source skipped for %s: %s", city_slug, exc)
            return empty_gdf()
    else:
        LOGGER.info("Microsoft source skipped for %s: no cached file", city_slug)
        return empty_gdf()
    standardized = standardize_microsoft(raw, place)
    assigned = assign_footprints_to_place(standardized, boundary)
    return dedupe_fallback_footprints(
        primary,
        assigned,
        overlap_ratio_threshold=config.microsoft_overlap_ratio_threshold,
    )


# Fetch OSM building attributes for small/debug AOIs when enabled.
def get_osm_buildings(boundary: gpd.GeoDataFrame, config: PipelineConfig) -> gpd.GeoDataFrame:
    """Fetch OSM building attributes for small/debug AOIs when enabled."""
    if not config.use_osm:
        return empty_gdf()
    try:
        import osmnx as ox

        raw = ox.features_from_polygon(boundary.geometry.iloc[0], tags={"building": True}).reset_index()
    except Exception as exc:
        LOGGER.warning("OSM source skipped: %s", exc)
        return empty_gdf()
    if raw.empty:
        return empty_gdf()
    raw = clean_geom(raw)
    if raw.empty:
        return empty_gdf()
    units = to_numeric_safe(raw.get("building:flats"), index=raw.index)
    for column in ("residential:units", "building:units", "units"):
        if column in raw.columns:
            units = units.combine_first(to_numeric_safe(raw[column], index=raw.index))
    osmid = raw.get("osmid", raw.get("id", pd.Series(raw.index, index=raw.index)))
    return gpd.GeoDataFrame(
        {
            "OSMID": osmid.astype("string"),
            "OSM_StructureType": raw.get("building", pd.Series(pd.NA, index=raw.index)),
            "Stories_OSM": to_numeric_safe(raw.get("building:levels"), index=raw.index),
            "Height_OSM": parse_height_meters(raw.get("height"), index=raw.index),
            "Units_OSM": units,
        },
        geometry=raw.geometry,
        crs=raw.crs,
    ).to_crs(epsg=4326)


# Attach OSM attributes to structures using representative-point containment.
def attach_osm_attributes(base: gpd.GeoDataFrame, osm: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Attach OSM attributes to structures using representative-point containment."""
    columns = ["OSMID", "OSM_StructureType", "Stories_OSM", "Height_OSM", "Units_OSM"]
    ensure_columns(
        base,
        {
            "OSMID": pd.NA,
            "OSM_StructureType": pd.NA,
            "Stories_OSM": np.nan,
            "Height_OSM": np.nan,
            "Units_OSM": np.nan,
        },
    )
    if base.empty or osm.empty:
        return base
    points = base[["StructureID", "geometry"]].copy()
    points["geometry"] = points.geometry.representative_point()
    joined = gpd.sjoin(points, osm[columns + ["geometry"]], how="left", predicate="within")
    joined = joined.drop_duplicates("StructureID").set_index("StructureID")
    base = base.set_index("StructureID")
    for column in columns:
        base[column] = joined[column].reindex(base.index).combine_first(base[column])
    return base.reset_index()


# Yield simple lon/lat tiles that intersect the AOI for NSI API requests.
def iter_boundary_tiles(boundary: gpd.GeoDataFrame, step_deg: float):
    """Yield simple lon/lat tiles that intersect the AOI for NSI API requests."""
    minx, miny, maxx, maxy = bounds_tuple(boundary)
    x_count = max(1, math.ceil((maxx - minx) / step_deg))
    y_count = max(1, math.ceil((maxy - miny) / step_deg))
    polygon = boundary.geometry.iloc[0]
    for ix in range(x_count):
        x0 = minx + ix * step_deg
        x1 = min(maxx, x0 + step_deg)
        for iy in range(y_count):
            y0 = miny + iy * step_deg
            y1 = min(maxy, y0 + step_deg)
            tile_geom = box(x0, y0, x1, y1)
            if tile_geom.intersects(polygon):
                yield gpd.GeoDataFrame(geometry=[tile_geom], crs=boundary.crs)


# Fetch USACE NSI point features over tiled AOI requests with de-duplication.
def get_nsi_structures(boundary: gpd.GeoDataFrame, config: PipelineConfig) -> gpd.GeoDataFrame:
    """Fetch USACE NSI point features over tiled AOI requests with de-duplication."""
    if not config.use_nsi:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    session = requests.Session()
    pieces = []
    seen_ids: set[str] = set()
    for tile in iter_boundary_tiles(boundary, config.nsi_tile_size_deg):
        body = json.loads(tile.to_json())
        try:
            response = session.post(
                NSI_STRUCTURES_URL,
                json=body,
                timeout=config.request_timeout_sec,
                verify=certifi.where(),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            LOGGER.warning("NSI tile skipped: %s", exc)
            continue
        features = payload.get("features", [])
        if not features:
            continue
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        if "fd_id" in gdf.columns:
            ids = gdf["fd_id"].astype(str)
            keep = ~ids.isin(seen_ids)
            seen_ids.update(ids[keep].tolist())
            gdf = gdf.loc[keep]
        pieces.append(gdf)
    if not pieces:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    nsi = gpd.GeoDataFrame(pd.concat(pieces, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    nsi = nsi[nsi.geometry.notna()].copy()
    return nsi[nsi.geometry.within(boundary.geometry.iloc[0])].reset_index(drop=True)


# Return the most common non-null value for groupby aggregation.
def _mode_value(series: pd.Series):
    """Return the most common non-null value for groupby aggregation."""
    values = series.dropna()
    mode = values.mode()
    return mode.iloc[0] if not mode.empty else (values.iloc[0] if not values.empty else pd.NA)


# Return the first non-null value for groupby aggregation.
def _first_value(series: pd.Series):
    """Return the first non-null value for groupby aggregation."""
    values = series.dropna()
    return values.iloc[0] if not values.empty else pd.NA


# Sum values while preserving NA when every value is missing.
def _sum_min_count(series: pd.Series):
    """Sum values while preserving NA when every value is missing."""
    return series.sum(min_count=1)


# Aggregate NSI point attributes into containing structure footprints.
def attach_nsi_attributes(base: gpd.GeoDataFrame, nsi: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Aggregate NSI point attributes into containing structure footprints."""
    columns = [
        "NSI_FD_ID",
        "NSI_RecordCount",
        "NSI_OccType",
        "NSI_DamageCategory",
        "NSI_NumStory",
        "NSI_ResUnits",
        "NSI_EmpNum",
        "NSI_Students",
        "NSI_Pop2AM",
        "NSI_Pop2PM",
    ]
    ensure_columns(
        base,
        {
            column: pd.NA
            if column in {"NSI_FD_ID", "NSI_OccType", "NSI_DamageCategory"}
            else np.nan
            for column in columns
        },
    )
    if base.empty or nsi.empty:
        return base

    fields = [
        "fd_id",
        "occtype",
        "st_damcat",
        "num_story",
        "resunits",
        "empnum",
        "students",
        "pop2amu65",
        "pop2amo65",
        "pop2pmu65",
        "pop2pmo65",
        "geometry",
    ]
    for field in fields:
        if field not in nsi.columns and field != "geometry":
            nsi[field] = np.nan
    nsi = nsi[fields].copy()
    for numeric in [
        "num_story",
        "resunits",
        "empnum",
        "students",
        "pop2amu65",
        "pop2amo65",
        "pop2pmu65",
        "pop2pmo65",
    ]:
        nsi[numeric] = to_numeric_safe(nsi[numeric], index=nsi.index)
    nsi["NSI_Pop2AM"] = nsi[["pop2amu65", "pop2amo65"]].sum(axis=1, min_count=1)
    nsi["NSI_Pop2PM"] = nsi[["pop2pmu65", "pop2pmo65"]].sum(axis=1, min_count=1)

    joined = gpd.sjoin(nsi, base[["StructureID", "geometry"]], how="inner", predicate="within")
    if joined.empty:
        return base
    aggregated = joined.groupby("StructureID").agg(
        NSI_FD_ID=("fd_id", _first_value),
        NSI_RecordCount=("fd_id", "count"),
        NSI_OccType=("occtype", _mode_value),
        NSI_DamageCategory=("st_damcat", _mode_value),
        NSI_NumStory=("num_story", "median"),
        NSI_ResUnits=("resunits", _sum_min_count),
        NSI_EmpNum=("empnum", _sum_min_count),
        NSI_Students=("students", _sum_min_count),
        NSI_Pop2AM=("NSI_Pop2AM", _sum_min_count),
        NSI_Pop2PM=("NSI_Pop2PM", _sum_min_count),
    )
    base = base.set_index("StructureID")
    for column in aggregated.columns:
        base[column] = aggregated[column].reindex(base.index).combine_first(base[column])
    return base.reset_index()


# Fetch ACS average household size for residential occupancy fallback.
def get_acs_household_size(place: pd.Series, config: PipelineConfig) -> tuple[float | None, str | None]:
    """Fetch ACS average household size for residential occupancy fallback."""
    if not config.use_census:
        return None, None
    session = requests.Session()
    for year in (2024, 2023, 2022, 2021, 2020):
        params = {
            "get": "NAME,B25010_001E",
            "for": f"place:{place['PlaceFP']}",
            "in": f"state:{place['StateFP']}",
        }
        try:
            response = session.get(
                CENSUS_ACS_URL.format(year=year),
                params=params,
                timeout=config.request_timeout_sec,
                verify=certifi.where(),
            )
            response.raise_for_status()
            rows = response.json()
        except Exception:
            continue
        if not rows or len(rows) < 2:
            continue
        header = rows[0]
        value_i = header.index("B25010_001E")
        value = pd.to_numeric(rows[1][value_i], errors="coerce")
        if pd.notna(value) and value > 0:
            return float(value), f"ACS {year} B25010_001E"
    return None, None


# Normalize source field names for resilient parcel column matching.
def normalize_field_name(value: str) -> str:
    """Normalize source field names for resilient parcel column matching."""
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


# Find a source column for a canonical parcel attribute using aliases.
def find_source_column(gdf: gpd.GeoDataFrame, source: dict, canonical_name: str) -> str | None:
    """Find a source column for a canonical parcel attribute using aliases."""
    field_map = source.get("field_map", {})
    configured = field_map.get(canonical_name) or field_map.get(canonical_name.lower())
    candidates = []
    if configured:
        candidates.extend(configured if isinstance(configured, list) else [configured])
    candidates.extend(PARCEL_FIELD_ALIASES[canonical_name])
    lookup = {normalize_field_name(column): column for column in gdf.columns}
    for candidate in candidates:
        column = lookup.get(normalize_field_name(candidate))
        if column:
            return column
    return None


# Resolve explicit or configured parcel sources by GEOID, slug, or label.
def source_for_place(place: pd.Series, config: PipelineConfig, source: dict | str | None) -> dict | None:
    """Resolve explicit or configured parcel sources by GEOID, slug, or label."""
    selected = source
    keys = [
        str(place["PlaceGEOID"]),
        slugify(place["City"], place["State"], "USA"),
        slugify(place["City"], place["State"]),
        slugify(place["City"]),
        f"{place['City']}, {place['State']}",
    ]
    for key in keys:
        if selected is None and key in config.parcel_sources:
            selected = config.parcel_sources[key]
    if selected is None:
        return None
    if isinstance(selected, str):
        return {"url": selected} if selected.lower().startswith("http") else {"path": selected}
    return dict(selected)


# Read local or ArcGIS parcel data, clip to AOI, and standardize columns.
def read_parcel_source(source: dict, boundary: gpd.GeoDataFrame, config: PipelineConfig) -> gpd.GeoDataFrame:
    """Read local or ArcGIS parcel data, clip to AOI, and standardize columns."""
    if "path" in source:
        path = Path(source["path"]).expanduser()
        if not path.exists():
            LOGGER.warning("Parcels skipped: file not found at %s", path)
            return empty_gdf()
        if path.suffix.lower() in {".parquet", ".geoparquet"}:
            parcels = gpd.read_parquet(path)
        else:
            try:
                parcels = gpd.read_file(path, bbox=bounds_tuple(boundary))
            except TypeError:
                parcels = gpd.read_file(path)
    elif "url" in source:
        url = source["url"].rstrip("/")
        query_url = url if url.endswith("/query") else f"{url}/query"
        minx, miny, maxx, maxy = bounds_tuple(boundary)
        page_size = int(source.get("page_size", 2000))
        features = []
        offset = 0
        while True:
            params = {
                "f": "geojson",
                "where": source.get("where", "1=1"),
                "outFields": source.get("out_fields", "*"),
                "returnGeometry": "true",
                "geometry": json.dumps(
                    {
                        "xmin": minx,
                        "ymin": miny,
                        "xmax": maxx,
                        "ymax": maxy,
                        "spatialReference": {"wkid": 4326},
                    }
                ),
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "outSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "resultRecordCount": page_size,
                "resultOffset": offset,
            }
            response = requests.get(
                query_url,
                params=params,
                timeout=config.request_timeout_sec,
                verify=certifi.where(),
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("features", [])
            if not batch:
                break
            features.extend(batch)
            offset += len(batch)
            if len(batch) < page_size and not payload.get("exceededTransferLimit"):
                break
        parcels = (
            gpd.GeoDataFrame.from_features(
                {"type": "FeatureCollection", "features": features}, crs="EPSG:4326"
            )
            if features
            else empty_gdf()
        )
    else:
        return empty_gdf()
    if parcels.crs is None:
        parcels = parcels.set_crs(source.get("crs", "EPSG:4326"))
    parcels = clean_geom(parcels.to_crs(epsg=4326))
    if parcels.empty:
        return empty_gdf()

    values = {}
    for canonical in PARCEL_FIELD_ALIASES:
        column = find_source_column(parcels, source, canonical)
        if column:
            values[canonical] = parcels[column]
        elif canonical in PARCEL_TEXT_COLUMNS:
            values[canonical] = pd.Series(pd.NA, index=parcels.index)
        else:
            values[canonical] = pd.Series(np.nan, index=parcels.index)
    out = gpd.GeoDataFrame(values, geometry=parcels.geometry, crs="EPSG:4326")
    out["ParcelSource"] = source.get("name") or source.get("path") or source.get("url")
    return out


# Attach parcel attributes to structures using representative-point containment.
def attach_parcel_attributes(
    base: gpd.GeoDataFrame,
    parcels: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Attach parcel attributes to structures using representative-point containment."""
    columns = [
        "ParcelID",
        "ParcelAddress",
        "ParcelLandUse",
        "ParcelZoning",
        "ParcelOwner",
        "ParcelAssessedValue",
        "ParcelYearBuilt",
        "ParcelSource",
        "ParcelMatchMethod",
    ]
    ensure_columns(
        base,
        {column: pd.NA if column in PARCEL_TEXT_COLUMNS else np.nan for column in columns},
    )
    if base.empty or parcels.empty:
        return base
    points = base[["StructureID", "geometry"]].copy()
    points["geometry"] = points.geometry.representative_point()
    joined = gpd.sjoin(points, parcels[[c for c in columns if c in parcels] + ["geometry"]], how="left", predicate="within")
    joined = joined.drop_duplicates("StructureID").set_index("StructureID")
    base = base.set_index("StructureID")
    for column in columns:
        if column == "ParcelMatchMethod":
            values = pd.Series(pd.NA, index=joined.index)
            values.loc[joined.get("ParcelSource", pd.Series(index=joined.index)).notna()] = "representative_point_within"
        else:
            values = joined.get(column, pd.Series(index=joined.index))
        base[column] = values.reindex(base.index).combine_first(base[column])
    return base.reset_index()


# Resolve, cache, read, and attach parcel data for one place when configured.
def load_and_attach_parcels(
    base: gpd.GeoDataFrame,
    place: pd.Series,
    boundary: gpd.GeoDataFrame,
    config: PipelineConfig,
    parcel_source: dict | str | None = None,
) -> gpd.GeoDataFrame:
    """Resolve, cache, read, and attach parcel data for one place when configured."""
    if not config.use_parcels:
        return base
    source = source_for_place(place, config, parcel_source)
    if source is None:
        return base
    cache_path = config.raw_dir / f"parcels_{place['PlaceGEOID']}.parquet"
    try:
        if source.get("url") and config.cache_remote_parcels and cache_path.exists() and not config.overwrite_raw:
            parcels = gpd.read_parquet(cache_path)
        else:
            parcels = read_parcel_source(source, boundary, config)
            if source.get("url") and config.cache_remote_parcels and not parcels.empty:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                parcels.to_parquet(cache_path, index=False)
    except Exception as exc:
        LOGGER.warning("Parcels skipped for %s: %s", place["PlaceGEOID"], exc)
        return base
    return attach_parcel_attributes(base, parcels)
