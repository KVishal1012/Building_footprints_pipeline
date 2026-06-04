from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger(__name__)


# Ensure the repository root is importable when the script is run from scripts/.
def add_repo_root_to_path() -> Path:
    """Ensure the repository root is importable when the script is run from scripts/."""
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root


# Load the local AI input module that contains model and run settings.
def load_input_module(module_name: str = "ai_inputs"):
    """Load the local AI input module that contains model and run settings."""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        raise RuntimeError(
            "Missing ai_inputs.py. Copy ai_inputs.example.py to ai_inputs.py "
            "and fill in model, training, and inference settings."
        ) from exc


# Read finalized training rows from parquet, csv, or json.
def read_training_frame(path: Path) -> pd.DataFrame:
    """Read finalized training rows from parquet, csv, or json."""
    if not path.exists():
        raise FileNotFoundError(f"Training data not found: {path}")
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".geoparquet"}:
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".json":
        return pd.read_json(path)
    raise ValueError(f"Unsupported training data file type: {path}")


# Train and save a model bundle based on ai_inputs.py settings.
def train_from_inputs(input_module) -> Path:
    """Train and save a model bundle based on ai_inputs.py settings."""
    from structures_pipeline.ai import save_model_bundle, train_model_bundle

    training_frame = read_training_frame(Path(input_module.TRAINING_DATA_PATH))
    bundle = train_model_bundle(
        training_frame,
        model_name=getattr(input_module, "MODEL_NAME", "us_structure_ai"),
        model_version=getattr(input_module, "MODEL_VERSION", "v1"),
        targets=list(getattr(input_module, "TARGETS", ["StructureType", "NumUnits", "NumStories", "OccupantCount"])),
    )
    output_path = save_model_bundle(bundle, Path(input_module.MODEL_BUNDLE_PATH))
    LOGGER.info("Saved AI model bundle: %s", output_path)
    return output_path


# Run pipeline inference based on ai_inputs.py settings.
def predict_from_inputs(input_module) -> dict:
    """Run pipeline inference based on ai_inputs.py settings."""
    from structures_pipeline.pipeline import run_pipeline

    target = input_module.get_target()
    return run_pipeline(
        place_specs=target.get("place_specs"),
        state_filters=target.get("state_filters"),
        all_us_cities=bool(target.get("all_us_cities", False)),
        config=input_module.PIPELINE_CONFIG,
    )


# Run train, predict, or train_and_predict based on the local input module.
def main() -> None:
    """Run train, predict, or train_and_predict based on the local input module."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    add_repo_root_to_path()
    input_module = load_input_module()
    run_mode = getattr(input_module, "RUN_MODE", "predict")
    if run_mode in {"train", "train_and_predict"}:
        train_from_inputs(input_module)
    result = {}
    if run_mode in {"predict", "train_and_predict"}:
        result = predict_from_inputs(input_module)
        dataframe = result.get("dataframe")
        if dataframe is not None:
            preview_rows = int(getattr(input_module, "DATAFRAME_PREVIEW_ROWS", 10))
            print(dataframe.head(preview_rows).to_string(index=False))
    if run_mode not in {"train", "predict", "train_and_predict"}:
        raise ValueError("RUN_MODE must be train, predict, or train_and_predict")
    if result.get("sql_export"):
        LOGGER.info("Exported SQL table: %s", result["sql_export"])


if __name__ == "__main__":
    main()
