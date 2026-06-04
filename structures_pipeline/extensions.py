from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from structures_pipeline.config import PipelineConfig

EXTENSION_SCHEMAS = {
    "flood": [
        "FloodZone",
        "BaseFloodElevation",
        "NearestWaterBody",
        "FloodExposureCategory",
        "BasementIndicator",
        "FloodSource",
        "FloodConfidence",
    ],
    "weather": [
        "WindZone",
        "HailRiskCategory",
        "TornadoRiskCategory",
        "RoofClass",
        "SevereWeatherExposure",
        "WeatherSource",
        "WeatherConfidence",
    ],
    "emergency_response": [
        "CriticalFacilityFlag",
        "CriticalFacilityType",
        "ShelterCapacity",
        "EmergencyOccupancyEstimate",
        "ResponsePriority",
        "EmergencySource",
        "EmergencyConfidence",
    ],
    "urban_planning": [
        "ZoningCode",
        "LandUseClass",
        "ParcelID",
        "YearBuilt",
        "AssessedValue",
        "PlanningSource",
        "PlanningConfidence",
    ],
    "oil_gas": [
        "NearestWellDistance_m",
        "NearestPipelineDistance_m",
        "NearestTankDistance_m",
        "OilGasExposureClass",
        "AssetBufferRelationship",
        "OilGasSource",
        "OilGasConfidence",
    ],
}

DEFAULT_EXTENSIONS = tuple(EXTENSION_SCHEMAS)


# Normalize configured extension names and reject misspellings early.
def resolve_domain_extensions(config: PipelineConfig) -> list[str]:
    """Normalize configured extension names and reject misspellings early."""
    requested = config.domain_extensions or list(DEFAULT_EXTENSIONS)
    normalized = [str(name).strip().lower().replace("-", "_").replace(" ", "_") for name in requested]
    unknown = sorted(set(normalized) - set(EXTENSION_SCHEMAS))
    if unknown:
        raise ValueError(f"Unsupported domain extension(s): {unknown}")
    return normalized


# Build one additive extension table keyed by StructureID.
def build_extension_table(gdf: gpd.GeoDataFrame, extension_name: str) -> pd.DataFrame:
    """Build one additive extension table keyed by StructureID."""
    normalized = str(extension_name).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in EXTENSION_SCHEMAS:
        raise ValueError(f"Unsupported domain extension: {extension_name}")
    if "StructureID" not in gdf.columns:
        raise ValueError("Domain extension tables require StructureID")
    frame = pd.DataFrame({"StructureID": gdf["StructureID"].astype(str)})
    for column in EXTENSION_SCHEMAS[normalized]:
        frame[column] = pd.NA
    return frame


# Build all configured extension tables without modifying the core structure frame.
def build_extension_tables(gdf: gpd.GeoDataFrame, config: PipelineConfig) -> dict[str, pd.DataFrame]:
    """Build all configured extension tables without modifying the core structure frame."""
    return {name: build_extension_table(gdf, name) for name in resolve_domain_extensions(config)}


# Write configured extension tables to CSV files for downstream onboarding and QA.
def write_extension_tables(gdf: gpd.GeoDataFrame, config: PipelineConfig) -> dict[str, Path]:
    """Write configured extension tables to CSV files for downstream onboarding and QA."""
    if gdf.empty or not config.domain_extensions:
        return {}
    output_dir = config.delivery_output_dir / "extensions"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, frame in build_extension_tables(gdf, config).items():
        path = output_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path
    return paths
