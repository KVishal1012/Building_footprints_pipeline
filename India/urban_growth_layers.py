from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


MODULE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ScenarioSpec:
    slug: str
    label: str
    value: str


SCENARIOS = [
    ScenarioSpec(
        "transit_oriented_infill_growth",
        "transit_oriented_infill_growth_proxy",
        "Dense-core infill proxy derived from current structure clusters.",
    ),
    ScenarioSpec(
        "blue_green_network_protection",
        "blue_green_network_protection_proxy",
        "Placeholder protection proxy until authoritative waterbody and wetland overlays are added.",
    ),
    ScenarioSpec(
        "peripheral_sprawl_along_highways",
        "peripheral_sprawl_along_highways_proxy",
        "Outer-envelope sprawl proxy derived from distance to the current urban core.",
    ),
    ScenarioSpec(
        "wetland_edge_encroachment",
        "wetland_edge_encroachment_proxy",
        "South-Chennai wetland-edge placeholder proxy until Pallikaranai and tank layers are sourced.",
    ),
    ScenarioSpec(
        "floodplain_lock_in",
        "floodplain_lock_in_proxy",
        "Coastal and low-side placeholder proxy until DEM and modeled flood layers are sourced.",
    ),
    ScenarioSpec(
        "heat_island_intensification_corridor",
        "heat_island_intensification_corridor_proxy",
        "Impervious-intensity proxy derived from local structure density and footprint area.",
    ),
    ScenarioSpec(
        "compound_risk_growth_hotspots",
        "compound_risk_growth_hotspots_proxy",
        "Combined proxy score across sprawl, wetland-edge, floodplain, and heat indicators.",
    ),
]

OUTPUT_COLUMNS = [
    "planning_label",
    "suitability_score",
    "planning_value",
    "scenario",
    "proxy_method",
    "source_authority",
    "geometry",
]


def _normalize(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").fillna(0)
    minimum = float(numeric.min())
    maximum = float(numeric.max())
    if maximum == minimum:
        return pd.Series(0.0, index=series.index)
    return (numeric - minimum) / (maximum - minimum)


def _select_proxy_features(
    structures: gpd.GeoDataFrame,
    score: pd.Series,
    spec: ScenarioSpec,
    *,
    quantile: float = 0.98,
) -> gpd.GeoDataFrame:
    threshold = float(score.quantile(quantile))
    selected = structures.loc[score >= threshold, ["geometry"]].copy()
    selected["suitability_score"] = score.loc[selected.index].clip(0, 1).round(4)
    if selected.empty:
        selected = structures.nlargest(1, "_proxy_area_m2")[["geometry"]].copy()
        selected["suitability_score"] = 1.0
    selected["planning_label"] = spec.label
    selected["planning_value"] = spec.value
    selected["scenario"] = spec.slug
    selected["proxy_method"] = "derived_from_structure_geometry_only"
    selected["source_authority"] = "derived_proxy_from_structures"
    return selected[OUTPUT_COLUMNS].reset_index(drop=True)


def build_urban_growth_layers(
    structures: gpd.GeoDataFrame,
    *,
    city: str = "Chennai",
    state: str = "Tamil Nadu",
) -> dict[str, gpd.GeoDataFrame]:
    if structures.empty:
        raise ValueError("structures must not be empty")
    if structures.crs is None:
        raise ValueError("structures must include a CRS")

    structures = structures.copy()
    structures = structures[structures.geometry.notna() & ~structures.geometry.is_empty]
    if structures.empty:
        raise ValueError("structures must include non-empty geometries")

    projected_crs = structures.estimate_utm_crs() or "EPSG:32644"
    work = structures.to_crs(projected_crs).reset_index(drop=True)
    work["_proxy_area_m2"] = work.geometry.area
    centroids = work.geometry.centroid
    x = pd.Series(centroids.x, index=work.index)
    y = pd.Series(centroids.y, index=work.index)
    center_x = float(x.median())
    center_y = float(y.median())
    distance_to_core = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
    distance_score = _normalize(distance_to_core)
    density_score = 1 - distance_score
    area_score = _normalize(work["_proxy_area_m2"])
    south_score = 1 - _normalize(y)
    east_score = _normalize(x)
    west_score = 1 - east_score
    edge_score = pd.concat(
        [east_score, west_score, _normalize(y), south_score], axis=1
    ).max(axis=1)
    heat_score = (0.55 * density_score + 0.45 * area_score).clip(0, 1)
    sprawl_score = (0.7 * distance_score + 0.3 * edge_score).clip(0, 1)
    wetland_score = (0.65 * south_score + 0.35 * east_score).clip(0, 1)
    flood_score = (0.55 * east_score + 0.45 * south_score).clip(0, 1)
    blue_green_score = (0.5 * wetland_score + 0.5 * flood_score).clip(0, 1)
    transit_infill_score = (0.7 * density_score + 0.3 * area_score).clip(0, 1)
    compound_score = (
        0.3 * sprawl_score + 0.25 * wetland_score + 0.25 * flood_score + 0.2 * heat_score
    ).clip(0, 1)

    scores = {
        "transit_oriented_infill_growth": transit_infill_score,
        "blue_green_network_protection": blue_green_score,
        "peripheral_sprawl_along_highways": sprawl_score,
        "wetland_edge_encroachment": wetland_score,
        "floodplain_lock_in": flood_score,
        "heat_island_intensification_corridor": heat_score,
        "compound_risk_growth_hotspots": compound_score,
    }

    layers = {}
    for spec in SCENARIOS:
        layer = _select_proxy_features(work, scores[spec.slug], spec).to_crs("EPSG:4326")
        layer["City"] = city
        layer["State"] = state
        layers[spec.slug] = layer
    return layers


def write_urban_growth_layers(
    structures_path: Path,
    output_dir: Path,
    *,
    city: str = "Chennai",
    state: str = "Tamil Nadu",
) -> dict[str, Path]:
    structures = gpd.read_parquet(structures_path)
    layers = build_urban_growth_layers(structures, city=city, state=state)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {}
    for slug, layer in layers.items():
        output_path = output_dir / f"{slug}.geojson"
        layer.to_file(output_path, driver="GeoJSON")
        paths[slug] = output_path
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Chennai urban-growth proxy planning layers."
    )
    parser.add_argument(
        "--structures",
        default=MODULE_DIR / "data/output/structures_master.parquet",
        type=Path,
        help="Canonical India structures GeoParquet.",
    )
    parser.add_argument(
        "--output-dir",
        default=MODULE_DIR / "data/processing/raw/urban_growth",
        type=Path,
        help="Directory for generated proxy GeoJSON layers.",
    )
    parser.add_argument("--city", default="Chennai")
    parser.add_argument("--state", default="Tamil Nadu")
    args = parser.parse_args()

    paths = write_urban_growth_layers(
        args.structures,
        args.output_dir,
        city=args.city,
        state=args.state,
    )
    for slug, path in paths.items():
        print(f"{slug}: {path}")


if __name__ == "__main__":
    main()
