from __future__ import annotations

from pathlib import Path

import pandas as pd

from structures_pipeline.ai.features import AI_FEATURE_COLUMNS, extract_ai_features

TARGETS = ["StructureType", "NumUnits", "NumStories", "OccupantCount"]
CLASSIFICATION_TARGETS = {"StructureType"}


# Load a serialized AI model bundle from disk.
def load_model_bundle(path: str | Path) -> dict:
    """Load a serialized AI model bundle from disk."""
    try:
        import joblib
    except ImportError as exc:
        raise RuntimeError("joblib is required to load AI model bundles") from exc
    return joblib.load(path)


# Save a serialized AI model bundle to disk.
def save_model_bundle(bundle: dict, path: str | Path) -> Path:
    """Save a serialized AI model bundle to disk."""
    try:
        import joblib
    except ImportError as exc:
        raise RuntimeError("joblib is required to save AI model bundles") from exc
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output_path)
    return output_path


# Build a scikit-learn estimator for one target.
def _build_estimator(target: str):
    """Build a scikit-learn estimator for one target."""
    try:
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.pipeline import Pipeline
    except ImportError as exc:
        raise RuntimeError("scikit-learn is required to train AI model bundles") from exc
    if target in CLASSIFICATION_TARGETS:
        model = RandomForestClassifier(n_estimators=50, random_state=42, min_samples_leaf=1)
    else:
        model = RandomForestRegressor(n_estimators=50, random_state=42, min_samples_leaf=1)
    return Pipeline([("vectorizer", DictVectorizer(sparse=False)), ("model", model)])


# Return rows with source-derived labels that are safe to use for supervised training.
def _training_rows(df: pd.DataFrame, target: str) -> pd.Series:
    """Return rows with source-derived labels that are safe to use for supervised training."""
    if target not in df.columns:
        return pd.Series(False, index=df.index)
    value = df[target]
    mask = value.notna()
    if value.dtype == object:
        mask &= value.astype(str).str.strip().ne("")
    prediction_kind = df.get("PredictionKind", pd.Series(pd.NA, index=df.index))
    mask &= prediction_kind.isna() | prediction_kind.astype(str).str.strip().eq("")
    return mask


# Train lightweight per-target estimators from finalized structure data.
def train_model_bundle(
    training_frame: pd.DataFrame,
    *,
    model_name: str = "us_structure_ai",
    model_version: str = "v1",
    feature_columns: list[str] | None = None,
    targets: list[str] | None = None,
) -> dict:
    """Train lightweight per-target estimators from finalized structure data."""
    columns = feature_columns or AI_FEATURE_COLUMNS
    target_names = targets or TARGETS
    features = extract_ai_features(training_frame, columns)
    estimators = {}
    for target in target_names:
        mask = _training_rows(training_frame, target)
        if int(mask.sum()) < 2:
            continue
        estimator = _build_estimator(target)
        train_features = features.loc[mask].to_dict(orient="records")
        train_target = training_frame.loc[mask, target]
        estimator.fit(train_features, train_target)
        estimators[target] = estimator
    return {
        "model_name": model_name,
        "model_version": model_version,
        "feature_columns": columns,
        "targets": target_names,
        "estimators": estimators,
    }
