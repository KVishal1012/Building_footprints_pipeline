from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from structures_pipeline.ai.features import AI_FEATURE_COLUMNS, extract_ai_features
from structures_pipeline.ai.training import load_model_bundle
from structures_pipeline.config import PipelineConfig

LOGGER = logging.getLogger(__name__)

TARGET_TO_PREDICTION_COLUMN = {
    "StructureType": "PredictedStructureType",
    "NumUnits": "PredictedNumUnits",
    "NumStories": "PredictedNumStories",
    "OccupantCount": "PredictedOccupantCount",
}

TARGET_TO_CONFIDENCE_COLUMN = {
    "StructureType": "StructureTypeConfidence",
    "NumUnits": "NumUnitsConfidence",
    "NumStories": "NumStoriesConfidence",
    "OccupantCount": "OccupantCountConfidence",
}

PREDICTION_COLUMNS = [
    "PredictedStructureType",
    "PredictedNumUnits",
    "PredictedNumStories",
    "PredictedOccupantCount",
    "PredictionKind",
    "PredictionModelName",
    "PredictionModelVersion",
    "PredictionConfidence",
    "PredictionFeaturesUsed",
    "AIDisclosureLevel",
    "PredictionSuppressionReason",
]


# Add empty prediction columns to preserve the final schema when AI is disabled.
def empty_prediction_columns(df: gpd.GeoDataFrame | pd.DataFrame) -> gpd.GeoDataFrame | pd.DataFrame:
    """Add empty prediction columns to preserve the final schema when AI is disabled."""
    if "CoverageTier" not in df.columns:
        df["CoverageTier"] = "Tier 3"
    else:
        missing_tier = df["CoverageTier"].isna() | df["CoverageTier"].astype(str).str.strip().eq("")
        df.loc[missing_tier, "CoverageTier"] = "Tier 3"
    for column in PREDICTION_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df


# Return true for rows where a suggest-only model is allowed to emit a prediction.
def prediction_candidate_mask(df: pd.DataFrame, target: str, min_confidence: float) -> pd.Series:
    """Return true for rows where a suggest-only model is allowed to emit a prediction."""
    value_missing = df[target].isna() if target in df.columns else pd.Series(True, index=df.index)
    if target in df.columns and df[target].dtype == object:
        value_missing |= df[target].astype(str).str.strip().eq("")
    confidence_column = TARGET_TO_CONFIDENCE_COLUMN.get(target)
    if confidence_column and confidence_column in df.columns:
        weak_confidence = pd.to_numeric(df[confidence_column], errors="coerce").fillna(0.0) < min_confidence
    else:
        weak_confidence = pd.Series(True, index=df.index)
    coverage_tier = df.get("CoverageTier", pd.Series("Tier 3", index=df.index)).fillna("Tier 3").astype(str)
    tier_1 = coverage_tier.eq("Tier 1")
    return value_missing | (~tier_1 & weak_confidence)


# Return the consumer-facing disclosure label for each coverage tier.
def ai_disclosure_for_tier(tier: str) -> str:
    """Return the consumer-facing disclosure label for each coverage tier."""
    tier = str(tier or "").strip()
    if tier == "Tier 1":
        return "authoritative_gap_fill_only"
    if tier == "Tier 2":
        return "moderate_ai_gap_fill"
    if tier == "Tier 3":
        return "mandatory_ai_disclosure"
    if tier == "Tier 4":
        return "estimated_heavy_ai_disclosure"
    return "mandatory_ai_disclosure"


# Predict with an estimator and return values plus row-level confidence.
def _predict_values(estimator, features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Predict with an estimator and return values plus row-level confidence."""
    predictions = estimator.predict(features)
    if hasattr(estimator, "predict_proba"):
        probabilities = estimator.predict_proba(features)
        confidence = np.max(probabilities, axis=1)
    else:
        confidence = np.ones(len(features), dtype="float64")
    return np.asarray(predictions), confidence


# Apply suggest-only AI predictions from a model bundle without overwriting source fields.
def apply_ai_predictions(
    gdf: gpd.GeoDataFrame,
    config: PipelineConfig,
    model_bundle: dict | None = None,
) -> gpd.GeoDataFrame:
    """Apply suggest-only AI predictions from a model bundle without overwriting source fields."""
    out = empty_prediction_columns(gdf.copy())
    if out.empty or not config.use_ai_predictions:
        return out
    if config.ai_prediction_mode != "suggest_only":
        raise ValueError("Only suggest_only AI prediction mode is supported in v1")

    bundle = model_bundle
    if bundle is None:
        model_path = Path(config.ai_model_dir) / "model_bundle.joblib"
        if not model_path.exists():
            LOGGER.warning("AI predictions skipped: missing model bundle at %s", model_path)
            return out
        bundle = load_model_bundle(model_path)

    feature_columns = list(bundle.get("feature_columns") or AI_FEATURE_COLUMNS)
    features = extract_ai_features(out, feature_columns)
    features_used = json.dumps(feature_columns, separators=(",", ":"))
    model_name = bundle.get("model_name", "us_structure_ai")
    model_version = bundle.get("model_version", "v1")
    estimators = dict(bundle.get("estimators") or {})

    for target, prediction_column in TARGET_TO_PREDICTION_COLUMN.items():
        estimator = estimators.get(target)
        if estimator is None:
            continue
        candidate_mask = prediction_candidate_mask(out, target, float(config.ai_min_confidence))
        if not candidate_mask.any():
            continue
        target_features = features.loc[candidate_mask]
        predictions, confidence = _predict_values(estimator, target_features)
        keep = confidence >= float(config.ai_min_confidence)
        suppressed_indexes = target_features.index[~keep]
        if len(suppressed_indexes):
            out.loc[suppressed_indexes, "PredictionSuppressionReason"] = "below_confidence_threshold"
        if not keep.any():
            continue
        indexes = target_features.index[keep]
        out.loc[indexes, prediction_column] = predictions[keep]
        current_conf = pd.to_numeric(out.loc[indexes, "PredictionConfidence"], errors="coerce")
        out.loc[indexes, "PredictionConfidence"] = np.fmax(current_conf.fillna(0.0), confidence[keep])
        out.loc[indexes, "PredictionKind"] = "ml_inference"
        out.loc[indexes, "PredictionModelName"] = model_name
        out.loc[indexes, "PredictionModelVersion"] = model_version
        out.loc[indexes, "PredictionFeaturesUsed"] = features_used
        out.loc[indexes, "AIDisclosureLevel"] = [
            ai_disclosure_for_tier(tier) for tier in out.loc[indexes, "CoverageTier"]
        ]
        out.loc[indexes, "PredictionSuppressionReason"] = pd.NA

    return out
