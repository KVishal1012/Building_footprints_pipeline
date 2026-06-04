import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from structures_pipeline.ai import apply_ai_predictions, extract_ai_features
from structures_pipeline.config import PipelineConfig


class ConstantEstimator:
    def __init__(self, value, confidence=0.9):
        self.value = value
        self.confidence = confidence

    def predict(self, features):
        return [self.value] * len(features)

    def predict_proba(self, features):
        return [[1 - self.confidence, self.confidence] for _ in range(len(features))]


def _base_frame():
    return gpd.GeoDataFrame(
        {
            "StructureID": ["known", "missing"],
            "StructureType": ["residential", pd.NA],
            "NumUnits": [2, pd.NA],
            "NumStories": [3, pd.NA],
            "OccupantCount": [5, pd.NA],
            "StructureTypeConfidence": [0.95, pd.NA],
            "NumUnitsConfidence": [0.95, pd.NA],
            "NumStoriesConfidence": [0.95, pd.NA],
            "OccupantCountConfidence": [0.95, pd.NA],
            "FootprintArea_m2": [100, 200],
            "FootprintArea_sqft": [1076, 2152],
            "City": ["Chicago", "Chicago"],
            "State": ["Illinois", "Illinois"],
            "RawDataSource": ["city_open_data", "city_open_data"],
            "FootprintSource": ["city_open_data", "city_open_data"],
            "StructureTypeRaw": ["residential", ""],
        },
        geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)],
        crs="EPSG:4326",
    )


def test_extract_ai_features_returns_stable_columns():
    features = extract_ai_features(_base_frame())

    assert "FootprintArea_m2" in features.columns
    assert "RawDataSource" in features.columns
    assert features.loc[1, "NumUnits"] == 0
    assert features.loc[0, "City"] == "Chicago"


def test_apply_ai_predictions_suggests_without_overwriting_authoritative_values():
    frame = _base_frame()
    config = PipelineConfig(use_ai_predictions=True, ai_min_confidence=0.7)
    bundle = {
        "model_name": "unit_test_model",
        "model_version": "v1",
        "feature_columns": ["FootprintArea_m2", "City", "RawDataSource"],
        "estimators": {
            "StructureType": ConstantEstimator("commercial"),
            "NumUnits": ConstantEstimator(10),
            "NumStories": ConstantEstimator(8),
            "OccupantCount": ConstantEstimator(20),
        },
    }

    predicted = apply_ai_predictions(frame, config, model_bundle=bundle)

    assert predicted.loc[0, "StructureType"] == "residential"
    assert pd.isna(predicted.loc[0, "PredictedStructureType"])
    assert predicted.loc[1, "PredictedStructureType"] == "commercial"
    assert predicted.loc[1, "PredictedNumUnits"] == 10
    assert predicted.loc[1, "PredictedNumStories"] == 8
    assert predicted.loc[1, "PredictedOccupantCount"] == 20
    assert predicted.loc[1, "PredictionKind"] == "ml_inference"
    assert predicted.loc[1, "PredictionModelName"] == "unit_test_model"


def test_apply_ai_predictions_suppresses_low_confidence_predictions():
    frame = _base_frame()
    config = PipelineConfig(use_ai_predictions=True, ai_min_confidence=0.7)
    bundle = {
        "model_name": "unit_test_model",
        "model_version": "v1",
        "feature_columns": ["FootprintArea_m2"],
        "estimators": {"StructureType": ConstantEstimator("commercial", confidence=0.4)},
    }

    predicted = apply_ai_predictions(frame, config, model_bundle=bundle)

    assert pd.isna(predicted.loc[1, "PredictedStructureType"])
    assert pd.isna(predicted.loc[1, "PredictionKind"])
    assert predicted.loc[1, "PredictionSuppressionReason"] == "below_confidence_threshold"


def test_tier_1_ai_only_fills_null_authoritative_fields():
    frame = _base_frame()
    frame["CoverageTier"] = ["Tier 1", "Tier 1"]
    frame["StructureTypeConfidence"] = [0.2, pd.NA]
    config = PipelineConfig(use_ai_predictions=True, ai_min_confidence=0.7)
    bundle = {
        "model_name": "unit_test_model",
        "model_version": "v1",
        "feature_columns": ["FootprintArea_m2"],
        "estimators": {"StructureType": ConstantEstimator("commercial")},
    }

    predicted = apply_ai_predictions(frame, config, model_bundle=bundle)

    assert pd.isna(predicted.loc[0, "PredictedStructureType"])
    assert predicted.loc[1, "PredictedStructureType"] == "commercial"
    assert predicted.loc[1, "AIDisclosureLevel"] == "authoritative_gap_fill_only"


def test_lower_tiers_allow_weak_confidence_suggestions_without_overwrite():
    frame = _base_frame()
    frame["CoverageTier"] = ["Tier 3", "Tier 3"]
    frame["StructureTypeConfidence"] = [0.2, pd.NA]
    config = PipelineConfig(use_ai_predictions=True, ai_min_confidence=0.7)
    bundle = {
        "model_name": "unit_test_model",
        "model_version": "v1",
        "feature_columns": ["FootprintArea_m2"],
        "estimators": {"StructureType": ConstantEstimator("commercial")},
    }

    predicted = apply_ai_predictions(frame, config, model_bundle=bundle)

    assert predicted.loc[0, "StructureType"] == "residential"
    assert predicted.loc[0, "PredictedStructureType"] == "commercial"
    assert predicted.loc[0, "AIDisclosureLevel"] == "mandatory_ai_disclosure"
