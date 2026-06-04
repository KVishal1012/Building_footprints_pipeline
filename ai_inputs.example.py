from __future__ import annotations

from pathlib import Path

from structures_pipeline.config import PipelineConfig

# Choose "train", "predict", or "train_and_predict".
RUN_MODE = "predict"

# Local model artifact path. The models/ directory is ignored by Git.
MODEL_DIR = Path("models/us_structure_ai")
MODEL_BUNDLE_PATH = MODEL_DIR / "model_bundle.joblib"
MODEL_NAME = "us_structure_ai"
MODEL_VERSION = "v1"

# Optional finalized training dataframe. Supports parquet, csv, or json.
TRAINING_DATA_PATH = Path("data/output/training/structures_training.parquet")

# AI behavior. V1 is suggest-only and never overwrites source-of-truth fields.
AI_MIN_CONFIDENCE = 0.70
AI_PREDICTION_MODE = "suggest_only"
TARGETS = ["StructureType", "NumUnits", "NumStories", "OccupantCount"]

# Pipeline target for inference runs.
PLACE_SPECS = [
    {"city": "Houston", "state": "Texas"},
]
STATE_FILTERS = None
ALL_US_CITIES = False

# Pipeline options for inference runs.
PIPELINE_CONFIG = PipelineConfig(
    data_dir=Path("data"),
    output_dir=Path("data/output"),
    raw_dir=Path("data/raw"),
    cache_dir=Path("cache"),
    download_missing=True,
    use_ai_predictions=True,
    ai_model_dir=MODEL_DIR,
    ai_prediction_mode=AI_PREDICTION_MODE,
    ai_min_confidence=AI_MIN_CONFIDENCE,
    return_dataframe=True,
    write_local_outputs=False,
)

DATAFRAME_PREVIEW_ROWS = 10


# Return the configured inference target selectors.
def get_target() -> dict:
    """Return the configured inference target selectors."""
    return {
        "place_specs": PLACE_SPECS,
        "state_filters": STATE_FILTERS,
        "all_us_cities": ALL_US_CITIES,
    }
