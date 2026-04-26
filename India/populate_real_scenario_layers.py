from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
from shapely.geometry import Point


MODULE_DIR = Path(__file__).resolve().parent
LOGGER = logging.getLogger("populate_real_scenario_layers")


SCENARIO_SUFFIXES = {
    "transit": "transit_oriented_growth_realworld_v1",
    "water": "blue_green_network_protection_realworld_v1",
    "wetlands": "wetland_edge_encroachment_realworld_v1",
    "flood": "floodplain_lock_in_realworld_v1",
    "heat": "heat_island_intensification_corridor_realworld_v1",
    "growth": "compound_risk_growth_hotspots_realworld_v1",
}


def setup_logging(level: str) -> None:
    numeric_level = getattr(logging, str(level).upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Unsupported logging level: {level!r}")
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def slugify(*parts: str) -> str:
    return "_".join(str(part).strip().lower().replace(" ", "_") for part in parts if part)


def city_slug(city: str, state: str, country: str) -> str:
    return slugify(city, state, country)


def scenario_id(city_slug_value: str, key: str) -> str:
    return f"{city_slug_value}_{SCENARIO_SUFFIXES[key]}"


def apply_context_scenarios(
    transit: gpd.GeoDataFrame,
    water: gpd.GeoDataFrame,
    wetlands: gpd.GeoDataFrame,
    city_slug_value: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    transit = transit.copy()
    water = water.copy()
    wetlands = wetlands.copy()
    transit["scenario"] = scenario_id(city_slug_value, "transit")
    water["scenario"] = scenario_id(city_slug_value, "water")
    wetlands["scenario"] = scenario_id(city_slug_value, "wetlands")
    return transit, water, wetlands


def normalize(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").fillna(0.0)
    minimum = float(numeric.min())
    maximum = float(numeric.max())
    if maximum == minimum:
        return pd.Series(0.0, index=series.index)
    return (numeric - minimum) / (maximum - minimum)


def ensure_valid_geometries(gdf: gpd.GeoDataFrame, *, name: str) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        raise ValueError(f"{name} has no CRS")
    out = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if out.empty:
        return out
    invalid = ~out.geometry.is_valid
    if invalid.any():
        out.loc[invalid, "geometry"] = out.loc[invalid, "geometry"].buffer(0)
    out = out[out.geometry.notna() & ~out.geometry.is_empty]
    return out


def get_city_boundary(city: str, state: str, country: str) -> gpd.GeoDataFrame:
    query = f"{city}, {state}, {country}"
    LOGGER.info("Fetching city boundary for %s", query)
    boundary = ox.geocode_to_gdf(query)
    if boundary.empty:
        raise ValueError(f"Boundary not found for {query}")
    boundary = boundary[["geometry"]].to_crs(epsg=4326)
    boundary = ensure_valid_geometries(boundary, name="boundary")
    if boundary.empty:
        raise ValueError(f"Boundary geometry empty for {query}")
    return boundary


def _pointify(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = gdf.copy()
    is_polygon = out.geom_type.isin(["Polygon", "MultiPolygon"])
    out.loc[is_polygon, "geometry"] = out.loc[is_polygon, "geometry"].representative_point()
    return out


def series_from(gdf: gpd.GeoDataFrame, column: str, default: str | None = None) -> pd.Series:
    if column in gdf.columns:
        return gdf[column]
    fill = pd.NA if default is None else default
    return pd.Series(fill, index=gdf.index)


def fetch_osm(boundary_polygon, tags: dict, name: str) -> gpd.GeoDataFrame:
    LOGGER.info("Downloading OSM %s features", name)
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            raw = ox.features_from_polygon(boundary_polygon, tags=tags).reset_index()
            break
        except Exception as exc:
            last_error = exc
            LOGGER.warning(
                "OSM %s fetch attempt %s failed: %s", name, attempt, exc
            )
            time.sleep(attempt * 2)
    else:
        LOGGER.warning("No OSM %s features fetched after retries: %s", name, last_error)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    if raw.empty:
        LOGGER.warning("No OSM features returned for %s", name)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    gdf = gpd.GeoDataFrame(raw, geometry="geometry", crs=raw.crs).to_crs(epsg=4326)
    gdf = ensure_valid_geometries(gdf, name=name)
    LOGGER.info("Fetched %s rows for %s", len(gdf), name)
    return gdf


def make_transit_layer(boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    tags = {
        "public_transport": ["station", "stop_position", "platform"],
        "railway": ["station", "halt", "tram_stop"],
        "amenity": ["bus_station"],
    }
    transit = fetch_osm(boundary.geometry.iloc[0], tags, "transit")
    if transit.empty:
        return gpd.GeoDataFrame(
            columns=["station_type", "station_name", "geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )

    transit = _pointify(transit)
    transit["station_type"] = (
        series_from(transit, "railway")
        .combine_first(series_from(transit, "public_transport"))
        .combine_first(series_from(transit, "amenity"))
        .fillna("station")
    )
    transit["station_name"] = series_from(transit, "name", "unnamed_station").fillna("unnamed_station")
    cols = ["station_type", "station_name", "geometry"]
    return ensure_valid_geometries(
        gpd.GeoDataFrame(transit[cols], geometry="geometry", crs=transit.crs),
        name="transit_layer",
    )


def _polygon_only(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon"])].copy()


def make_water_layer(boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    tags = {
        "natural": ["water", "bay"],
        "water": True,
        "landuse": ["reservoir", "basin"],
        "waterway": ["riverbank"],
    }
    water = fetch_osm(boundary.geometry.iloc[0], tags, "water")
    water = _polygon_only(water)
    if water.empty:
        return gpd.GeoDataFrame(
            columns=["water_type", "water_name", "geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )
    water["water_type"] = (
        series_from(water, "water")
        .combine_first(series_from(water, "natural"))
        .combine_first(series_from(water, "waterway"))
        .combine_first(series_from(water, "landuse"))
        .fillna("waterbody")
    )
    water["water_name"] = series_from(water, "name", "unnamed_waterbody").fillna("unnamed_waterbody")
    water = _pointify(water)
    cols = ["water_type", "water_name", "geometry"]
    return ensure_valid_geometries(
        gpd.GeoDataFrame(water[cols], geometry="geometry", crs=water.crs),
        name="water_layer",
    )


def make_wetland_layer(boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    tags = {"natural": ["wetland"], "wetland": True}
    wetlands = fetch_osm(boundary.geometry.iloc[0], tags, "wetlands")
    wetlands = _polygon_only(wetlands)
    if wetlands.empty:
        return gpd.GeoDataFrame(
            columns=["wetland_type", "wetland_name", "geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )
    wetlands["wetland_type"] = series_from(wetlands, "wetland").combine_first(
        series_from(wetlands, "natural")
    ).fillna("wetland")
    wetlands["wetland_name"] = series_from(wetlands, "name", "unnamed_wetland").fillna("unnamed_wetland")
    wetlands = _pointify(wetlands)
    cols = ["wetland_type", "wetland_name", "geometry"]
    return ensure_valid_geometries(
        gpd.GeoDataFrame(wetlands[cols], geometry="geometry", crs=wetlands.crs),
        name="wetland_layer",
    )


def build_grid(boundary: gpd.GeoDataFrame, cell_size_m: float) -> gpd.GeoDataFrame:
    projected_crs = boundary.estimate_utm_crs() or "EPSG:32644"
    work_boundary = boundary.to_crs(projected_crs)
    minx, miny, maxx, maxy = work_boundary.total_bounds
    xs = np.arange(minx, maxx + cell_size_m, cell_size_m)
    ys = np.arange(miny, maxy + cell_size_m, cell_size_m)
    cells = []
    for x0 in xs[:-1]:
        for y0 in ys[:-1]:
            cells.append(
                {
                    "geometry": Point(x0 + (cell_size_m / 2), y0 + (cell_size_m / 2)).buffer(
                        cell_size_m / np.sqrt(np.pi)
                    )
                }
            )
    grid = gpd.GeoDataFrame(cells, geometry="geometry", crs=projected_crs)
    grid = gpd.overlay(grid, work_boundary, how="intersection")
    grid["grid_id"] = [f"g_{i:08d}" for i in range(len(grid))]
    return ensure_valid_geometries(grid.to_crs(epsg=4326), name="grid")


def distance_to_nearest(
    points: gpd.GeoDataFrame, targets: gpd.GeoDataFrame, projected_crs: str
) -> pd.Series:
    if targets.empty:
        return pd.Series(np.nan, index=points.index, dtype="float64")
    point_proj = points.to_crs(projected_crs)
    target_proj = targets.to_crs(projected_crs)
    nearest = gpd.sjoin_nearest(
        point_proj[["geometry"]],
        target_proj[["geometry"]],
        how="left",
        distance_col="distance_m",
    )
    distance_series = pd.to_numeric(nearest["distance_m"], errors="coerce")
    min_by_point = distance_series.groupby(level=0).min()
    return min_by_point.reindex(points.index)


def build_derived_scenario_layers(
    boundary: gpd.GeoDataFrame,
    transit: gpd.GeoDataFrame,
    water: gpd.GeoDataFrame,
    wetlands: gpd.GeoDataFrame,
    structures_path: Path,
    city: str,
    state: str,
    city_slug_value: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    if not structures_path.exists():
        raise FileNotFoundError(f"Structures file not found: {structures_path}")
    structures = gpd.read_parquet(structures_path)
    structures = ensure_valid_geometries(structures.to_crs(epsg=4326), name="structures")
    if structures.empty:
        raise ValueError("Structures file has no valid geometries")

    grid = build_grid(boundary, cell_size_m=500)
    projected_crs = grid.estimate_utm_crs() or "EPSG:32644"
    grid_projected = grid.to_crs(projected_crs)
    centroids = gpd.GeoDataFrame(
        {"grid_id": grid["grid_id"]},
        geometry=grid_projected.geometry.centroid,
        crs=projected_crs,
    )

    structures_projected = structures.to_crs(projected_crs)
    structure_points = gpd.GeoDataFrame(
        {"sid": structures.get("StructureID", pd.Series(range(len(structures))))},
        geometry=structures_projected.geometry.centroid,
        crs=projected_crs,
    )
    joined = gpd.sjoin(
        structure_points,
        grid_projected[["grid_id", "geometry"]],
        how="left",
        predicate="within",
    )
    structure_counts = joined["grid_id"].value_counts()
    grid["structure_count"] = grid["grid_id"].map(structure_counts).fillna(0).astype(float)
    grid["structure_density_score"] = normalize(grid["structure_count"])

    transit_points = _pointify(transit) if not transit.empty else transit
    grid["dist_transit_m"] = distance_to_nearest(centroids, transit_points, projected_crs)
    grid["dist_water_m"] = distance_to_nearest(centroids, water, projected_crs)
    grid["dist_wetland_m"] = distance_to_nearest(centroids, wetlands, projected_crs)
    grid["transit_access_score"] = 1 - normalize(grid["dist_transit_m"].fillna(grid["dist_transit_m"].max()))
    grid["water_proximity_score"] = 1 - normalize(grid["dist_water_m"].fillna(grid["dist_water_m"].max()))
    grid["wetland_proximity_score"] = 1 - normalize(grid["dist_wetland_m"].fillna(grid["dist_wetland_m"].max()))

    flood_prob = (
        0.5 * grid["water_proximity_score"] + 0.35 * grid["wetland_proximity_score"] + 0.15 * grid["structure_density_score"]
    ).clip(0, 1)
    heat_score = (
        0.65 * grid["structure_density_score"] + 0.35 * (1 - grid["water_proximity_score"])
    ).clip(0, 1)
    suitability = (
        0.45 * grid["transit_access_score"] + 0.35 * (1 - flood_prob) + 0.20 * (1 - heat_score)
    ).clip(0, 1)

    point_grid = gpd.GeoDataFrame(
        {"grid_id": grid["grid_id"]},
        geometry=grid_projected.geometry.centroid,
        crs=projected_crs,
    ).to_crs(epsg=4326)

    flood_layer = point_grid[["geometry"]].copy()
    flood_layer["scenario"] = scenario_id(city_slug_value, "flood")
    flood_layer["probability"] = flood_prob.round(4)
    flood_layer["depth_m"] = (0.25 + 2.75 * flood_layer["probability"]).round(2)
    flood_layer["risk_class"] = pd.cut(
        flood_layer["probability"],
        bins=[-0.001, 0.33, 0.66, 1.0],
        labels=["low", "medium", "high"],
    ).astype("string")

    heat_layer = point_grid[["geometry"]].copy()
    heat_layer["score"] = heat_score.round(4)
    heat_layer["index_value"] = (100 * heat_layer["score"]).round(1)
    heat_layer["scenario"] = scenario_id(city_slug_value, "heat")
    heat_layer["heat_class"] = pd.cut(
        heat_layer["score"],
        bins=[-0.001, 0.33, 0.66, 1.0],
        labels=["cooler_zone", "warming_zone", "heat_intensification_zone"],
    ).astype("string")

    growth_layer = point_grid[["geometry"]].copy()
    growth_layer["scenario"] = scenario_id(city_slug_value, "growth")
    growth_layer["suitability_score"] = suitability.round(4)
    growth_layer["planning_value"] = (
        "Transit-access weighted suitability penalized by flood and heat risk"
    )
    growth_layer["planning_label"] = pd.cut(
        growth_layer["suitability_score"],
        bins=[-0.001, 0.33, 0.66, 1.0],
        labels=["low_suitability", "moderate_suitability", "high_suitability"],
    ).astype("string")

    flood_layer["City"] = city
    flood_layer["State"] = state
    heat_layer["City"] = city
    heat_layer["State"] = state
    growth_layer["City"] = city
    growth_layer["State"] = state

    return (
        ensure_valid_geometries(flood_layer, name="flood_layer"),
        ensure_valid_geometries(heat_layer, name="heat_layer"),
        ensure_valid_geometries(growth_layer, name="growth_layer"),
    )


def write_layer(gdf: gpd.GeoDataFrame, path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    validated = ensure_valid_geometries(gdf, name=name)
    if validated.empty:
        LOGGER.warning("%s is empty; writing empty GeoJSON at %s", name, path)
    validated.to_file(path, driver="GeoJSON")
    LOGGER.info("Wrote %s rows to %s", len(validated), path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Populate real-world city scenario layers from OSM and structure context."
    )
    parser.add_argument("--city", default="Chennai")
    parser.add_argument("--state", default="Tamil Nadu")
    parser.add_argument("--country", default="India")
    parser.add_argument(
        "--structures",
        type=Path,
        default=MODULE_DIR / "data/output/structures_master.parquet",
        help="Structure GeoParquet used for derived scenario metrics.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=MODULE_DIR / "data/processing/raw/scenarios",
        help="Directory to write scenario GeoJSON layers.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    city_slug_value = city_slug(args.city, args.state, args.country)
    boundary = get_city_boundary(args.city, args.state, args.country)
    transit = make_transit_layer(boundary)
    water = make_water_layer(boundary)
    wetlands = make_wetland_layer(boundary)
    transit, water, wetlands = apply_context_scenarios(
        transit, water, wetlands, city_slug_value
    )
    flood, heat, growth = build_derived_scenario_layers(
        boundary=boundary,
        transit=transit,
        water=water,
        wetlands=wetlands,
        structures_path=args.structures,
        city=args.city,
        state=args.state,
        city_slug_value=city_slug_value,
    )

    write_layer(
        transit,
        args.output_dir / f"{city_slug_value}_transit_stations.geojson",
        f"{city_slug_value}_transit_stations",
    )
    write_layer(
        water,
        args.output_dir / f"{city_slug_value}_waterbodies.geojson",
        f"{city_slug_value}_waterbodies",
    )
    write_layer(
        wetlands,
        args.output_dir / f"{city_slug_value}_wetlands.geojson",
        f"{city_slug_value}_wetlands",
    )
    write_layer(
        flood,
        args.output_dir / f"{city_slug_value}_flood_hazard_zones.geojson",
        f"{city_slug_value}_flood_hazard_zones",
    )
    write_layer(
        heat,
        args.output_dir / f"{city_slug_value}_heat_intensity.geojson",
        f"{city_slug_value}_heat_intensity",
    )
    write_layer(
        growth,
        args.output_dir / f"{city_slug_value}_growth_suitability.geojson",
        f"{city_slug_value}_growth_suitability",
    )


if __name__ == "__main__":
    main()
