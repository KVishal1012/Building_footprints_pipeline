from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

from structures_pipeline.config import PipelineConfig
from structures_pipeline.coverage import build_gap_registry, build_source_completeness
from structures_pipeline.utils import json_safe, utc_now_iso
from structures_pipeline.validation import validate_release_gates


# Convert path dictionaries into JSON-safe strings while preserving nested metadata.
def _json_paths(paths: dict) -> dict:
    """Convert path dictionaries into JSON-safe strings while preserving nested metadata."""
    converted = {}
    for key, value in paths.items():
        if isinstance(value, Path):
            converted[key] = str(value)
        elif isinstance(value, dict):
            converted[key] = _json_paths(value)
        else:
            converted[key] = json_safe(value)
    return converted


# Build compact structure-database package metadata for consumer handoff.
def build_release_manifest(
    gdf: gpd.GeoDataFrame,
    config: PipelineConfig,
    *,
    manifest_path: Path | None = None,
    delivery_paths: dict | None = None,
    coverage_paths: dict | None = None,
    extension_paths: dict | None = None,
    sql_export: dict | None = None,
    metrics: list[dict] | None = None,
) -> dict:
    """Build compact structure-database package metadata for consumer handoff."""
    frame = gdf if gdf is not None else gpd.GeoDataFrame()
    release_id = config.release_id or f"sid-{utc_now_iso().replace(':', '').replace('+', 'Z')}"
    row_count = int(len(frame))
    prediction_kind_counts = {}
    if "PredictionKind" in frame.columns:
        prediction_kind_counts = frame["PredictionKind"].fillna("none").astype(str).value_counts().to_dict()
    coverage_tier_counts = {}
    if "CoverageTier" in frame.columns:
        coverage_tier_counts = frame["CoverageTier"].fillna("unknown").astype(str).value_counts().to_dict()
    release_gates = validate_release_gates(frame) if row_count else {"status": "passed", "checks": {}, "blockers": []}
    source_completeness = build_source_completeness(frame) if row_count else []
    gap_registry = []
    if row_count and {"City", "State"}.issubset(frame.columns):
        gap_registry = build_gap_registry(frame, config).to_dict("records")
    frame_refresh_timestamp = None
    if row_count and "data_refresh_timestamp" in frame.columns:
        values = frame["data_refresh_timestamp"].dropna().astype(str)
        frame_refresh_timestamp = values.max() if not values.empty else None

    manifest = {
        "release_id": release_id,
        "generated_at": utc_now_iso(),
        "product": "Structure Intelligence Database",
        "schema_version": "2.0",
        "branch": "US_Structure_AI",
        "row_count": row_count,
        "quality_contract": {
            "canonical_database": config.canonical_database,
            "source_of_truth": config.canonical_database.get("canonical_table", "public.structures"),
            "ai_policy": "suggest_only_never_overwrite",
            "provenance_required": True,
            "audit_trail_required": True,
            "release_gates": release_gates,
        },
        "freshness": {
            "data_refresh_timestamp": config.data_refresh_timestamp or frame_refresh_timestamp,
            "last_refreshed": config.refresh_metadata.get("last_refreshed") or (
                frame["last_refreshed"].dropna().astype(str).max()
                if row_count and "last_refreshed" in frame.columns and not frame["last_refreshed"].dropna().empty
                else None
            ),
            "source_as_of": config.refresh_metadata.get("source_as_of") or (
                frame["source_as_of"].dropna().astype(str).max()
                if row_count and "source_as_of" in frame.columns and not frame["source_as_of"].dropna().empty
                else config.source_version
            ),
            "refresh_cadence": config.refresh_metadata.get("refresh_cadence"),
        },
        "coverage": {
            "tier_counts": coverage_tier_counts,
            "gap_registry": json_safe(gap_registry),
            "source_completeness": json_safe(source_completeness),
            "coverage_outputs": _json_paths(coverage_paths or {}),
        },
        "ai": {
            "enabled": bool(config.use_ai_predictions),
            "mode": config.ai_prediction_mode,
            "min_confidence": float(config.ai_min_confidence),
            "prediction_kind_counts": prediction_kind_counts,
        },
        "delivery": {
            "primary_api": "supabase_rest_api",
            "formats": list(config.delivery_formats),
            "outputs": _json_paths(delivery_paths or {}),
            "sql_server_export": json_safe(sql_export),
            "postgis_export": json_safe(config.postgis_export),
        },
        "extensions": {
            "enabled": list(config.domain_extensions),
            "outputs": _json_paths(extension_paths or {}),
        },
        "pipeline_manifest": str(manifest_path) if manifest_path else None,
        "city_metrics": json_safe(metrics or []),
        "config": json_safe(config.__dict__),
    }
    manifest["quality_contract"]["release_gates"] = validate_release_gates(frame, manifest=manifest) if row_count else release_gates
    return manifest


# Write the release package manifest used by versioned distribution workflows.
def write_release_manifest(
    gdf: gpd.GeoDataFrame,
    config: PipelineConfig,
    **kwargs,
) -> Path:
    """Write the release package manifest used by versioned distribution workflows."""
    config.release_output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_release_manifest(gdf, config, **kwargs)
    path = config.release_output_dir / "release_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return path
