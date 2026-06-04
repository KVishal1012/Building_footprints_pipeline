from __future__ import annotations

import pandas as pd

AI_FEATURE_COLUMNS = [
    "FootprintArea_m2",
    "FootprintArea_sqft",
    "NumUnits",
    "NumStories",
    "OccupantCount",
    "StructureTypeConfidence",
    "NumUnitsConfidence",
    "NumStoriesConfidence",
    "OccupantCountConfidence",
    "City",
    "State",
    "RawDataSource",
    "FootprintSource",
    "StructureTypeRaw",
    "StructureTypeSource",
    "NumUnitsSource",
    "NumStoriesSource",
    "OccupantCountSource",
]

NUMERIC_FEATURES = {
    "FootprintArea_m2",
    "FootprintArea_sqft",
    "NumUnits",
    "NumStories",
    "OccupantCount",
    "StructureTypeConfidence",
    "NumUnitsConfidence",
    "NumStoriesConfidence",
    "OccupantCountConfidence",
}


# Extract model-ready tabular features from finalized structure rows.
def extract_ai_features(df: pd.DataFrame, feature_columns: list[str] | None = None) -> pd.DataFrame:
    """Extract model-ready tabular features from finalized structure rows."""
    columns = feature_columns or AI_FEATURE_COLUMNS
    features = pd.DataFrame(index=df.index)
    for column in columns:
        if column in df.columns:
            features[column] = df[column]
        else:
            features[column] = pd.NA
        if column in NUMERIC_FEATURES:
            features[column] = pd.to_numeric(features[column], errors="coerce").fillna(0.0)
        else:
            features[column] = features[column].fillna("").astype(str)
    return features
