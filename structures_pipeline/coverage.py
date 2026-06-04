from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from structures_pipeline.config import PipelineConfig

COVERAGE_TIERS = {"Tier 1", "Tier 2", "Tier 3", "Tier 4"}


# Assign a documented coverage tier to one city/state group.
def assign_coverage_tier(city: str, state: str, group: pd.DataFrame, config: PipelineConfig) -> str:
    """Assign a documented coverage tier to one city/state group."""
    overrides = dict(config.coverage_config.get("tier_overrides") or {})
    key = f"{city}, {state}".lower()
    slug = f"{city}_{state}".lower().replace(" ", "_")
    if key in overrides:
        return overrides[key]
    if slug in overrides:
        return overrides[slug]

    sources = set(group.get("RawDataSource", pd.Series(dtype="object")).dropna().astype(str).str.lower())
    sources |= set(group.get("FootprintSource", pd.Series(dtype="object")).dropna().astype(str).str.lower())
    has_authority = any(
        token in source
        for source in sources
        for token in ("pluto", "assessor", "authoritative", "parcel")
    )
    has_nsi = group.get("OccupantCountSource", pd.Series(dtype="object")).astype(str).str.lower().eq("nsi").any()
    has_overture = any("overture" in source for source in sources)
    has_osm = any("osm" in source for source in sources)

    if has_authority and has_nsi and has_overture:
        return "Tier 1"
    if has_authority and (has_nsi or has_overture):
        return "Tier 2"
    if has_nsi and has_overture:
        return "Tier 3"
    if has_overture or has_osm:
        return "Tier 4"
    return "Tier 3"


# Build one gap-registry row per city/state with attribute completeness metrics.
def build_gap_registry(gdf: gpd.GeoDataFrame, config: PipelineConfig) -> pd.DataFrame:
    """Build one gap-registry row per city/state with attribute completeness metrics."""
    if gdf.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    for (city, state), group in gdf.groupby(["City", "State"], dropna=False):
        raw_sources = group.get("RawDataSource", pd.Series(dtype="object")).dropna().astype(str)
        rows.append(
            {
                "City": city,
                "State": state,
                "CoverageTier": assign_coverage_tier(str(city), str(state), group, config),
                "row_count": int(len(group)),
                "structure_type_completeness": float(group["StructureType"].notna().mean()),
                "num_units_completeness": float(group["NumUnits"].notna().mean()),
                "num_stories_completeness": float(group["NumStories"].notna().mean()),
                "occupant_count_completeness": float(group["OccupantCount"].notna().mean()),
                "has_authoritative_source": bool(raw_sources.str.contains("pluto|assessor|authoritative|parcel", case=False, regex=True).any()),
                "has_nsi": bool(group["OccupantCountSource"].astype(str).str.lower().eq("nsi").any()),
                "has_overture": bool(raw_sources.str.contains("overture", case=False, regex=True).any()),
                "has_osm": bool(raw_sources.str.contains("osm", case=False, regex=True).any()),
                "last_refreshed": group["last_refreshed"].dropna().max() if "last_refreshed" in group else pd.NA,
                "source_as_of": group["source_as_of"].dropna().max() if "source_as_of" in group else pd.NA,
            }
        )
    return pd.DataFrame(rows)


# Add city coverage tiers to each structure so downstream AI policy can be deterministic.
def apply_coverage_tiers(gdf: gpd.GeoDataFrame, config: PipelineConfig) -> gpd.GeoDataFrame:
    """Add city coverage tiers to each structure so downstream AI policy can be deterministic."""
    if gdf.empty:
        return gdf
    out = gdf.copy()
    if "CoverageTier" not in out.columns:
        out["CoverageTier"] = pd.NA
    for (city, state), group in out.groupby(["City", "State"], dropna=False):
        tier = assign_coverage_tier(str(city), str(state), group, config)
        out.loc[group.index, "CoverageTier"] = tier
    return out


# Write coverage metadata as CSV plus JSON for API-ready consumers.
def write_coverage_outputs(gdf: gpd.GeoDataFrame, config: PipelineConfig) -> dict:
    """Write coverage metadata as CSV plus JSON for API-ready consumers."""
    registry = build_gap_registry(gdf, config)
    output_dir = config.delivery_output_dir / "coverage"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "gap_registry.csv"
    json_path = output_dir / "coverage.json"
    registry.to_csv(csv_path, index=False)
    registry.to_json(json_path, orient="records", indent=2)
    return {"gap_registry": csv_path, "coverage_json": json_path}
