from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from structures_pipeline.attributes import finalize_attributes
from structures_pipeline.census import parse_place, place_slug, resolve_census_year, select_places
from structures_pipeline.config import PipelineConfig
from structures_pipeline.geometry import normalize_boundary
from structures_pipeline.sources import (
    attach_nsi_attributes,
    attach_osm_attributes,
    attach_baseline_proximity,
    buffered_baseline_boundary,
    get_acs_household_size,
    get_nsi_structures,
    get_osm_buildings,
    load_and_attach_parcels,
    load_microsoft_fallback,
    load_overture_buildings,
    load_sql_footprints,
    read_sql_baseline_source,
    resolve_overture_release,
)
from structures_pipeline.utils import json_safe, utc_now_iso
from structures_pipeline.validation import validate_output, write_city_metrics

LOGGER = logging.getLogger(__name__)


def boundary_for_place(place: pd.Series) -> gpd.GeoDataFrame:
    attrs = place.drop(labels=["geometry"]).to_dict()
    return gpd.GeoDataFrame([attrs], geometry=[place.geometry], crs="EPSG:4326")


def city_output_path(config: PipelineConfig, place: pd.Series) -> Path:
    slug = place_slug(place)
    return (
        config.cities_output_dir
        / str(place["StateFP"])
        / f"{place['PlaceGEOID']}_{slug}_structures.parquet"
    )


def build_place_structures(
    place: pd.Series,
    config: PipelineConfig | None = None,
    overture_release: str | None = None,
    parcel_source: dict | str | None = None,
    write_output: bool = True,
) -> tuple[gpd.GeoDataFrame, dict]:
    config = config or PipelineConfig()
    config.ensure_dirs()
    boundary = normalize_boundary(boundary_for_place(place))
    LOGGER.info("Building structures for %s, %s", place["City"], place["State"])

    baseline = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    baseline_source = config.sql_baseline_source
    baseline_buffer_meters = float(baseline_source.get("buffer_meters", 0) or 0)
    if baseline_source:
        baseline = read_sql_baseline_source(baseline_source, config)
        boundary = buffered_baseline_boundary(baseline, baseline_buffer_meters)
        LOGGER.info(
            "Using %s SQL baseline features buffered by %s meters for %s",
            len(baseline),
            baseline_buffer_meters,
            place["PlaceGEOID"],
        )

    sql_footprints = load_sql_footprints(place, boundary, config)
    overture = load_overture_buildings(place, boundary, config, overture_release)
    primary_pieces = [frame for frame in [sql_footprints, overture] if not frame.empty]
    if primary_pieces:
        primary = gpd.GeoDataFrame(
            pd.concat(primary_pieces, ignore_index=True),
            geometry="geometry",
            crs="EPSG:4326",
        )
    else:
        primary = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    microsoft = load_microsoft_fallback(place, boundary, config, primary)
    if primary.empty:
        base = microsoft
    elif microsoft.empty:
        base = primary
    else:
        base = gpd.GeoDataFrame(
            pd.concat([primary, microsoft], ignore_index=True),
            geometry="geometry",
            crs="EPSG:4326",
        )

    osm = get_osm_buildings(boundary, config)
    base = attach_osm_attributes(base, osm)
    nsi = get_nsi_structures(boundary, config)
    base = attach_nsi_attributes(base, nsi)
    base = load_and_attach_parcels(base, place, boundary, config, parcel_source)

    household_size, acs_source = get_acs_household_size(place, config)
    final = finalize_attributes(
        base,
        place=place,
        census_household_size=household_size,
        acs_source=acs_source,
        overture_release=overture_release,
        census_year=resolve_census_year(config),
    )
    if baseline_source:
        final = attach_baseline_proximity(final, baseline, baseline_buffer_meters)
    metrics = validate_output(final) if not final.empty else {"row_count": 0}
    output_path = city_output_path(config, place)
    metrics.update(
        {
            "PlaceGEOID": place["PlaceGEOID"],
            "City": place["City"],
            "State": place["State"],
            "StateFP": place["StateFP"],
            "output_path": str(output_path),
        }
    )
    if write_output:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        final.to_parquet(output_path, index=False)
    return final, metrics


def write_master_dataset(city_paths: list[Path], config: PipelineConfig) -> Path | None:
    if not city_paths:
        return None
    config.master_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = config.master_output_dir / "structures_master.parquet"
    try:
        import duckdb

        quoted_paths = ", ".join("'" + str(path).replace("'", "''") + "'" for path in city_paths)
        con = duckdb.connect()
        try:
            con.execute(
                f"""
                COPY (
                    SELECT * FROM read_parquet([{quoted_paths}], union_by_name = true)
                )
                TO '{str(output_path).replace("'", "''")}' (FORMAT PARQUET)
                """
            )
        finally:
            con.close()
    except Exception as exc:
        LOGGER.warning("DuckDB master write failed, falling back to GeoPandas concat: %s", exc)
        frames = [gpd.read_parquet(path) for path in city_paths]
        combined = gpd.GeoDataFrame(
            pd.concat(frames, ignore_index=True),
            geometry="geometry",
            crs=frames[0].crs if frames else "EPSG:4326",
        )
        combined.to_parquet(output_path, index=False)
    return output_path


def write_manifest(
    config: PipelineConfig,
    *,
    places: gpd.GeoDataFrame,
    metrics: list[dict],
    city_paths: list[Path],
    master_path: Path | None,
    overture_release: str | None,
) -> Path:
    manifest = {
        "run_started_at": utc_now_iso(),
        "country": config.country,
        "coverage": "Census places, 50 states plus DC",
        "source_version_mode": config.source_version,
        "overture_release": overture_release,
        "census_year": resolve_census_year(config),
        "row_count": int(sum(item.get("row_count", 0) for item in metrics)),
        "place_count": int(len(places)),
        "city_outputs": [str(path) for path in city_paths],
        "master_output": str(master_path) if master_path else None,
        "config": json_safe(config.__dict__),
    }
    path = config.manifest_dir / "latest_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return path


def build_places(
    places: gpd.GeoDataFrame,
    config: PipelineConfig | None = None,
    parcel_sources: dict[str, dict] | None = None,
) -> dict:
    config = config or PipelineConfig()
    config.ensure_dirs()
    overture_release = resolve_overture_release(config)
    metrics: list[dict] = []
    city_paths: list[Path] = []

    for _, place in places.iterrows():
        source = None
        if parcel_sources:
            source = parcel_sources.get(str(place["PlaceGEOID"])) or parcel_sources.get(place_slug(place))
        _, city_metrics = build_place_structures(
            place,
            config=config,
            overture_release=overture_release,
            parcel_source=source,
            write_output=True,
        )
        metrics.append(city_metrics)
        city_paths.append(Path(city_metrics["output_path"]))

    master_path = write_master_dataset(city_paths, config)
    qa_path = config.qa_dir / "city_metrics.parquet"
    write_city_metrics(metrics, qa_path)
    manifest_path = write_manifest(
        config,
        places=places,
        metrics=metrics,
        city_paths=city_paths,
        master_path=master_path,
        overture_release=overture_release,
    )
    return {
        "city_paths": city_paths,
        "master_path": master_path,
        "qa_path": qa_path,
        "manifest_path": manifest_path,
        "metrics": metrics,
    }


def run_pipeline(
    *,
    place_specs: list[dict[str, str]] | None = None,
    state_filters: list[str] | None = None,
    all_us_cities: bool = False,
    config: PipelineConfig | None = None,
) -> dict:
    config = config or PipelineConfig()
    config.ensure_dirs()
    places = select_places(
        config,
        place_specs=place_specs,
        state_filters=state_filters,
        all_us_cities=all_us_cities,
    )
    if places.empty:
        raise ValueError("No Census places selected")
    return build_places(places, config=config)


def build_city_structures(
    city: str,
    state: str,
    config: PipelineConfig | None = None,
    parcel_source: dict | str | None = None,
) -> gpd.GeoDataFrame:
    config = config or PipelineConfig()
    places = select_places(config, place_specs=[{"city": city, "state": state}])
    overture_release = resolve_overture_release(config)
    final, _ = build_place_structures(
        places.iloc[0],
        config=config,
        overture_release=overture_release,
        parcel_source=parcel_source,
        write_output=True,
    )
    return final


def build_many_cities(
    cities: list[dict[str, str]],
    config: PipelineConfig | None = None,
) -> gpd.GeoDataFrame:
    config = config or PipelineConfig()
    place_specs = [{"city": item["city"], "state": item["state"]} for item in cities]
    result = run_pipeline(place_specs=place_specs, config=config)
    if result["master_path"] and Path(result["master_path"]).exists():
        return gpd.read_parquet(result["master_path"])
    return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")


def parse_place_arg(value: str) -> dict[str, str]:
    return parse_place(value)
