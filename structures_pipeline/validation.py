from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS


# Validate required schema, geometry health, IDs, and key fill-rate metrics.
def validate_output(gdf: gpd.GeoDataFrame) -> dict:
    """Validate required schema, geometry health, IDs, and key fill-rate metrics."""
    missing = [column for column in REQUIRED_OUTPUT_COLUMNS if column not in gdf.columns]
    if missing:
        raise ValueError(f"Output is missing required columns: {missing}")
    if gdf.crs is None:
        raise ValueError("Output GeoDataFrame has no CRS")
    if gdf.crs.to_epsg() != 4326:
        raise ValueError(f"Output CRS must be EPSG:4326, got {gdf.crs}")
    if gdf["StructureID"].duplicated().any():
        duplicates = int(gdf["StructureID"].duplicated().sum())
        raise ValueError(f"Output has duplicate StructureID values: {duplicates}")
    attribute_sources = {
        "StructureType": "StructureTypeSource",
        "NumStories": "NumStoriesSource",
        "NumUnits": "NumUnitsSource",
        "OccupantCount": "OccupantCountSource",
    }
    for value_column, source_column in attribute_sources.items():
        has_value = gdf[value_column].notna() & gdf[value_column].astype(str).str.strip().ne("")
        missing_source = gdf[source_column].isna() | gdf[source_column].astype(str).str.strip().eq("")
        if (has_value & missing_source).any():
            raise ValueError(f"Output has {value_column} values without {source_column}")

    geometry_not_empty = gdf.geometry.notna() & ~gdf.geometry.is_empty
    geometry_valid = gdf.geometry.is_valid.fillna(False)
    positive_area = pd.to_numeric(gdf["FootprintArea_m2"], errors="coerce").gt(0)
    invalid_geometry_count = int((~geometry_not_empty | ~geometry_valid).sum())
    non_positive_area_count = int((~positive_area).sum())
    if invalid_geometry_count:
        raise ValueError(f"Output has invalid/empty geometries: {invalid_geometry_count}")
    if non_positive_area_count:
        raise ValueError(f"Output has non-positive footprint areas: {non_positive_area_count}")

    return {
        "row_count": int(len(gdf)),
        "invalid_geometry_count": invalid_geometry_count,
        "duplicate_structure_id_count": int(gdf["StructureID"].duplicated().sum()),
        "non_positive_area_count": non_positive_area_count,
        "attribute_fill_structure_type": float(gdf["StructureType"].notna().mean()) if len(gdf) else 0.0,
        "attribute_fill_num_units": float(gdf["NumUnits"].notna().mean()) if len(gdf) else 0.0,
        "attribute_fill_num_stories": float(gdf["NumStories"].notna().mean()) if len(gdf) else 0.0,
        "attribute_fill_occupants": float(gdf["OccupantCount"].notna().mean()) if len(gdf) else 0.0,
        "nsi_match_rate": float(gdf["OccupantCountSource"].eq("nsi").mean()) if len(gdf) else 0.0,
        "acs_fallback_count": int(gdf["OccupantCountSource"].eq("acs").sum()),
        "overture_count": int(gdf["FootprintSource"].eq("overture").sum()),
        "microsoft_fallback_count": int(gdf["FootprintSource"].eq("microsoft_fallback").sum()),
    }


# Write accumulated per-city QA metrics to a parquet file.
def write_city_metrics(metrics: list[dict], path: Path) -> None:
    """Write accumulated per-city QA metrics to a parquet file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(metrics).to_parquet(path, index=False)
