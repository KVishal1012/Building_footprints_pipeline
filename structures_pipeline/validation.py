from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS
from structures_pipeline.utils import json_safe

CORE_ATTRIBUTE_SOURCES = {
    "StructureType": "StructureTypeSource",
    "NumStories": "NumStoriesSource",
    "NumUnits": "NumUnitsSource",
    "OccupantCount": "OccupantCountSource",
}
AUDIT_FRESHNESS_COLUMNS = [
    "created_at",
    "updated_at",
    "updated_by",
    "change_log",
    "data_refresh_timestamp",
    "last_refreshed",
    "source_as_of",
]
SOURCE_COLUMNS = ["LoadSource", "RawDataSource", "FootprintSource"]
AI_SOURCE_PATTERN = r"\b(?:ai|ml_inference|model_prediction|prediction)\b"
PREDICTION_METADATA_COLUMNS = [
    "PredictionKind",
    "PredictionModelName",
    "PredictionModelVersion",
    "PredictionConfidence",
    "PredictionFeaturesUsed",
    "AIDisclosureLevel",
]


# Return a boolean mask for null or blank values in a dataframe column.
def _empty_mask(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return a boolean mask for null or blank values in a dataframe column."""
    if column not in frame.columns:
        return pd.Series(True, index=frame.index)
    return frame[column].isna() | frame[column].astype(str).str.strip().eq("")


# Return true where a canonical source label is actually an AI/prediction label.
def _ai_source_mask(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return true where a canonical source label is actually an AI/prediction label."""
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].fillna("").astype(str).str.lower().str.contains(AI_SOURCE_PATTERN, regex=True)


# Build a structured pass/fail report for production release gates.
def validate_release_gates(
    gdf: gpd.GeoDataFrame,
    *,
    manifest: dict | None = None,
) -> dict:
    """Build a structured pass/fail report for production release gates."""
    checks: dict[str, dict] = {}
    blockers: list[str] = []

    def record(name: str, passed: bool, detail: dict | None = None) -> None:
        checks[name] = {"passed": bool(passed), **(detail or {})}
        if not passed:
            blockers.append(name)

    missing = [column for column in REQUIRED_OUTPUT_COLUMNS if column not in gdf.columns]
    record("required_schema", not missing, {"missing_columns": missing})
    if missing:
        return {"status": "failed", "checks": checks, "blockers": blockers}

    record("crs_epsg_4326", gdf.crs is not None and gdf.crs.to_epsg() == 4326, {"crs": str(gdf.crs)})
    duplicate_count = int(gdf["StructureID"].duplicated().sum())
    record("unique_structure_id", duplicate_count == 0, {"duplicate_count": duplicate_count})

    geometry_not_empty = gdf.geometry.notna() & ~gdf.geometry.is_empty
    geometry_valid = gdf.geometry.is_valid.fillna(False)
    invalid_geometry_count = int((~geometry_not_empty | ~geometry_valid).sum())
    record("valid_geometry", invalid_geometry_count == 0, {"invalid_geometry_count": invalid_geometry_count})

    non_positive_area_count = int((~pd.to_numeric(gdf["FootprintArea_m2"], errors="coerce").gt(0)).sum())
    record("positive_footprint_area", non_positive_area_count == 0, {"non_positive_area_count": non_positive_area_count})

    empty_audit = {column: int(_empty_mask(gdf, column).sum()) for column in AUDIT_FRESHNESS_COLUMNS}
    record("audit_freshness_complete", not any(empty_audit.values()), {"empty_counts": empty_audit})

    empty_sources = {column: int(_empty_mask(gdf, column).sum()) for column in SOURCE_COLUMNS}
    record("source_fields_complete", not any(empty_sources.values()), {"empty_counts": empty_sources})

    coverage_empty_count = int(_empty_mask(gdf, "CoverageTier").sum())
    record("coverage_tier_complete", coverage_empty_count == 0, {"empty_count": coverage_empty_count})

    datasource_failures = {}
    for value_column, source_column in CORE_ATTRIBUTE_SOURCES.items():
        has_value = ~_empty_mask(gdf, value_column)
        missing_source = _empty_mask(gdf, source_column)
        failure_count = int((has_value & missing_source).sum())
        if failure_count:
            datasource_failures[source_column] = failure_count
    record("attribute_datasources_complete", not datasource_failures, {"failure_counts": datasource_failures})

    ai_source_failures = {
        column: int(_ai_source_mask(gdf, column).sum())
        for column in SOURCE_COLUMNS + list(CORE_ATTRIBUTE_SOURCES.values())
    }
    ai_source_failures = {column: count for column, count in ai_source_failures.items() if count}
    record("ai_not_authoritative_source", not ai_source_failures, {"failure_counts": ai_source_failures})

    prediction_values = pd.Series(False, index=gdf.index)
    for column in ("PredictedStructureType", "PredictedNumUnits", "PredictedNumStories", "PredictedOccupantCount"):
        if column in gdf.columns:
            prediction_values |= ~_empty_mask(gdf, column)
    prediction_metadata_failures = {
        column: int((prediction_values & _empty_mask(gdf, column)).sum())
        for column in PREDICTION_METADATA_COLUMNS
    }
    prediction_metadata_failures = {
        column: count for column, count in prediction_metadata_failures.items() if count
    }
    record("ai_prediction_metadata_complete", not prediction_metadata_failures, {"failure_counts": prediction_metadata_failures})

    if manifest is not None:
        manifest_missing = [
            key
            for key in ("release_id", "generated_at", "quality_contract", "freshness", "coverage", "delivery")
            if key not in manifest or manifest.get(key) is None
        ]
        freshness = dict(manifest.get("freshness") or {})
        if not freshness.get("data_refresh_timestamp"):
            manifest_missing.append("freshness.data_refresh_timestamp")
        record("release_manifest_complete", not manifest_missing, {"missing": manifest_missing})

    return {"status": "passed" if not blockers else "failed", "checks": checks, "blockers": blockers}


# Validate required schema, geometry health, IDs, and key fill-rate metrics.
def validate_output(gdf: gpd.GeoDataFrame) -> dict:
    """Validate required schema, geometry health, IDs, and key fill-rate metrics."""
    gates = validate_release_gates(gdf)
    if gates["status"] != "passed":
        for name in gates["blockers"]:
            detail = gates["checks"][name]
            if name == "required_schema":
                raise ValueError(f"Output is missing required columns: {detail['missing_columns']}")
            if name == "crs_epsg_4326":
                raise ValueError(f"Output CRS must be EPSG:4326, got {detail['crs']}")
            if name == "unique_structure_id":
                raise ValueError(f"Output has duplicate StructureID values: {detail['duplicate_count']}")
            if name == "valid_geometry":
                raise ValueError(f"Output has invalid/empty geometries: {detail['invalid_geometry_count']}")
            if name == "positive_footprint_area":
                raise ValueError(f"Output has non-positive footprint areas: {detail['non_positive_area_count']}")
            if name == "audit_freshness_complete":
                column = next(column for column, count in detail["empty_counts"].items() if count)
                raise ValueError(f"Output has empty audit/freshness field: {column}")
            if name == "source_fields_complete":
                column = next(column for column, count in detail["empty_counts"].items() if count)
                raise ValueError(f"Output has empty source field: {column}")
            if name == "coverage_tier_complete":
                raise ValueError("Output has empty CoverageTier values")
            if name == "attribute_datasources_complete":
                column = next(iter(detail["failure_counts"]))
                raise ValueError(f"Output has populated attributes without {column}")
            if name == "ai_not_authoritative_source":
                column = next(iter(detail["failure_counts"]))
                raise ValueError(f"AI/model values cannot be used as {column}")
            if name == "ai_prediction_metadata_complete":
                column = next(iter(detail["failure_counts"]))
                raise ValueError(f"AI predictions are missing required metadata: {column}")
        raise ValueError(f"Output failed release gates: {gates['blockers']}")

    return {
        "row_count": int(len(gdf)),
        "release_gates": gates,
        "invalid_geometry_count": gates["checks"]["valid_geometry"]["invalid_geometry_count"],
        "duplicate_structure_id_count": int(gdf["StructureID"].duplicated().sum()),
        "non_positive_area_count": gates["checks"]["positive_footprint_area"]["non_positive_area_count"],
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
    normalized = []
    for metric in metrics:
        row = {}
        for key, value in metric.items():
            if isinstance(value, (dict, list, tuple)):
                row[key] = json.dumps(json_safe(value), sort_keys=True)
            else:
                row[key] = value
        normalized.append(row)
    pd.DataFrame(normalized).to_parquet(path, index=False)
