from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from structures_pipeline.config import PipelineConfig
from structures_pipeline.sources import dataframe_for_sql_export

SUPPORTED_DELIVERY_FORMATS = {"csv", "parquet", "geojson", "postgis"}


# Export the final dataframe to configured non-SQL-Server delivery formats.
def export_delivery_formats(gdf: gpd.GeoDataFrame, config: PipelineConfig) -> dict[str, Path | dict]:
    """Export the final dataframe to configured non-SQL-Server delivery formats."""
    if gdf.empty or not config.delivery_formats:
        return {}
    output_dir = config.delivery_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path | dict] = {}

    for fmt in config.delivery_formats:
        normalized = fmt.lower()
        if normalized not in SUPPORTED_DELIVERY_FORMATS:
            raise ValueError(f"Unsupported delivery format: {fmt}")
        if normalized == "csv":
            path = output_dir / "structures.csv"
            dataframe_for_sql_export(gdf).to_csv(path, index=False)
            paths["csv"] = path
        elif normalized == "parquet":
            path = output_dir / "structures.parquet"
            gdf.to_parquet(path, index=False)
            paths["parquet"] = path
        elif normalized == "geojson":
            path = output_dir / "structures.geojson"
            gdf.to_file(path, driver="GeoJSON")
            paths["geojson"] = path
        elif normalized == "postgis":
            paths["postgis"] = export_postgis_compatible(gdf, config)
    return paths


# Export a PostGIS-compatible table or return a dry-run table shape when no connection is configured.
def export_postgis_compatible(gdf: gpd.GeoDataFrame, config: PipelineConfig) -> dict:
    """Export a PostGIS-compatible table or return a dry-run table shape when no connection is configured."""
    export_config = config.postgis_export
    table = export_config.get("table", "structures")
    geometry_column = export_config.get("geometry_column", "geometry_wkt")
    frame = dataframe_for_sql_export(gdf, geometry_column=geometry_column)
    connection = export_config.get("connection")
    if not connection:
        return {
            "table": table,
            "rows_prepared": int(len(frame)),
            "geometry_column": geometry_column,
            "mode": "prepared_only",
        }
    try:
        from sqlalchemy import create_engine
    except ImportError as exc:
        raise RuntimeError("sqlalchemy is required for PostGIS export") from exc
    schema, _, table_name = table.rpartition(".")
    engine = create_engine(connection)
    frame.to_sql(
        table_name or table,
        engine,
        schema=schema or None,
        if_exists=export_config.get("if_exists", "append"),
        index=False,
        chunksize=int(export_config.get("chunksize") or 1000),
    )
    return {
        "table": table,
        "rows_exported": int(len(frame)),
        "geometry_column": geometry_column,
        "mode": "exported",
    }
