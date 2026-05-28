from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from structures_pipeline.config import PipelineConfig
from structures_pipeline.constants import (
    CENSUS_GAZETTEER_PLACE_URL,
    CENSUS_TIGER_PLACE_URL,
    STATE_ABBR_TO_NAME,
    STATEFP_TO_ABBR,
    STATEFP_TO_NAME,
    US_STATEFPS_50_DC,
)
from structures_pipeline.geometry import clean_geom
from structures_pipeline.utils import normalize_place_name, normalize_state_name, slugify, statefp_for_state

LOGGER = logging.getLogger(__name__)


# Parse a CLI place string into normalized city/state fields.
def parse_place(value: str) -> dict[str, str]:
    """Parse a CLI place string into normalized city/state fields."""
    if "," not in value:
        raise ValueError("Use 'City, State', for example 'Chicago, Illinois'")
    city, state = value.rsplit(",", 1)
    return {"city": city.strip(), "state": normalize_state_name(state.strip())}


# Return the configured Census vintage as an integer.
def resolve_census_year(config: PipelineConfig) -> int:
    """Return the configured Census vintage as an integer."""
    return int(config.census_year)


# Download a source file only when missing or overwrite is enabled.
def _download(url: str, path: Path, config: PipelineConfig) -> None:
    """Download a source file only when missing or overwrite is enabled."""
    if path.exists() and not config.overwrite_raw:
        return
    if not config.download_missing:
        raise FileNotFoundError(f"Missing cached source and downloads disabled: {path}")
    LOGGER.info("Downloading %s", url)
    path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=config.request_timeout_sec)
    response.raise_for_status()
    path.write_bytes(response.content)


# Build the local cache path for one state's TIGER/Line place zip.
def tiger_place_zip_path(config: PipelineConfig, statefp: str) -> Path:
    """Build the local cache path for one state's TIGER/Line place zip."""
    year = resolve_census_year(config)
    return config.raw_dir / "census" / "tiger" / str(year) / f"tl_{year}_{statefp}_place.zip"


# Build the local cache path for the national Census gazetteer zip.
def gazetteer_zip_path(config: PipelineConfig) -> Path:
    """Build the local cache path for the national Census gazetteer zip."""
    year = resolve_census_year(config)
    return config.raw_dir / "census" / "gazetteer" / str(year) / f"{year}_Gaz_place_national.zip"


# Load the national Census gazetteer once for optional place metadata joins.
def load_gazetteer(config: PipelineConfig) -> pd.DataFrame:
    """Load the national Census gazetteer once for optional place metadata joins."""
    year = resolve_census_year(config)
    path = gazetteer_zip_path(config)
    url = CENSUS_GAZETTEER_PLACE_URL.format(year=year)
    try:
        _download(url, path, config)
    except Exception as exc:
        LOGGER.warning("Gazetteer metadata skipped: %s", exc)
        return pd.DataFrame()

    with zipfile.ZipFile(path) as archive:
        txt_names = [name for name in archive.namelist() if name.lower().endswith(".txt")]
        if not txt_names:
            return pd.DataFrame()
        with archive.open(txt_names[0]) as fh:
            gazetteer = pd.read_csv(fh, sep="\t", dtype=str)
    gazetteer.columns = [column.strip() for column in gazetteer.columns]
    if "GEOID" not in gazetteer.columns:
        return pd.DataFrame()
    keep = [
        column
        for column in ["GEOID", "INTPTLAT", "INTPTLONG", "ALAND_SQMI", "AWATER_SQMI"]
        if column in gazetteer.columns
    ]
    return gazetteer[keep].rename(
        columns={
            "GEOID": "PlaceGEOID",
            "INTPTLAT": "GazetteerLat",
            "INTPTLONG": "GazetteerLon",
            "ALAND_SQMI": "GazetteerLandSqMi",
            "AWATER_SQMI": "GazetteerWaterSqMi",
        }
    )


# Normalize TIGER/Line place features to the pipeline's place inventory schema.
def normalize_places(raw: gpd.GeoDataFrame, year: int) -> gpd.GeoDataFrame:
    """Normalize TIGER/Line place features to the pipeline's place inventory schema."""
    raw = raw.to_crs(epsg=4326) if raw.crs else raw.set_crs(epsg=4326)
    raw = raw[raw["STATEFP"].isin(US_STATEFPS_50_DC)].copy()
    places = gpd.GeoDataFrame(
        {
            "PlaceGEOID": raw["GEOID"].astype(str),
            "StateFP": raw["STATEFP"].astype(str),
            "PlaceFP": raw["PLACEFP"].astype(str),
            "City": raw["NAME"].astype(str),
            "PlaceNameLSAD": raw.get("NAMELSAD", raw["NAME"]).astype(str),
            "LSAD": raw.get("LSAD", pd.Series(pd.NA, index=raw.index)),
            "FunctionalStatus": raw.get("FUNCSTAT", pd.Series(pd.NA, index=raw.index)),
            "CensusYear": year,
        },
        geometry=raw.geometry,
        crs="EPSG:4326",
    )
    places["State"] = places["StateFP"].map(STATEFP_TO_NAME)
    places["StateAbbr"] = places["StateFP"].map(STATEFP_TO_ABBR)
    return clean_geom(places).reset_index(drop=True)


# Load and normalize all Census places for one state FIPS code.
def load_state_places(
    config: PipelineConfig,
    statefp: str,
    gazetteer: pd.DataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Load and normalize all Census places for one state FIPS code."""
    year = resolve_census_year(config)
    path = tiger_place_zip_path(config, statefp)
    url = CENSUS_TIGER_PLACE_URL.format(year=year, statefp=statefp)
    _download(url, path, config)
    raw = gpd.read_file(path)
    places = normalize_places(raw, year)
    gazetteer = load_gazetteer(config) if gazetteer is None else gazetteer
    if not gazetteer.empty:
        places = places.merge(gazetteer, on="PlaceGEOID", how="left")
        places = gpd.GeoDataFrame(places, geometry="geometry", crs="EPSG:4326")
    return places.reset_index(drop=True)


# Load Census places for requested states or the full 50-state-plus-DC set.
def load_place_inventory(
    config: PipelineConfig,
    states: list[str] | None = None,
) -> gpd.GeoDataFrame:
    """Load Census places for requested states or the full 50-state-plus-DC set."""
    if states:
        statefps = [statefp_for_state(state) if not state.isdigit() else state for state in states]
    else:
        statefps = list(US_STATEFPS_50_DC)
    gazetteer = load_gazetteer(config)
    pieces = [load_state_places(config, statefp, gazetteer) for statefp in statefps]
    if not pieces:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(
        pd.concat(pieces, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )


# Resolve CLI target options to the exact Census place rows to process.
def select_places(
    config: PipelineConfig,
    place_specs: list[dict[str, str]] | None = None,
    state_filters: list[str] | None = None,
    all_us_cities: bool = False,
) -> gpd.GeoDataFrame:
    """Resolve CLI target options to the exact Census place rows to process."""
    if all_us_cities:
        return load_place_inventory(config)
    if state_filters:
        return load_place_inventory(config, state_filters)
    if not place_specs:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    specs_by_state: dict[str, list[dict[str, str]]] = {}
    for spec in place_specs:
        state_name = normalize_state_name(spec["state"])
        specs_by_state.setdefault(state_name, []).append(spec)

    pieces = []
    gazetteer = load_gazetteer(config)
    for state_name, specs in specs_by_state.items():
        places = load_state_places(config, statefp_for_state(state_name), gazetteer)
        normalized_city = places["City"].map(normalize_place_name)
        normalized_lsad = places["PlaceNameLSAD"].map(normalize_place_name)
        for spec in specs:
            target = normalize_place_name(spec["city"])
            candidates = places[
                normalized_city.eq(target) | normalized_lsad.eq(target)
            ].copy()
            if candidates.empty:
                raise ValueError(f"Census place not found: {spec['city']}, {state_name}")
            if len(candidates) > 1:
                candidates = candidates.sort_values(["FunctionalStatus", "PlaceGEOID"])
            pieces.append(candidates.iloc[[0]])

    return gpd.GeoDataFrame(
        pd.concat(pieces, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )


# Return the canonical output slug for a Census place row.
def place_slug(place: pd.Series) -> str:
    """Return the canonical output slug for a Census place row."""
    return slugify(place["City"], place["State"], "USA")
