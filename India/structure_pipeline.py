from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import shutil
import ssl
import subprocess
import sys
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.request import urlopen

import certifi
import geopandas as gpd
import mercantile
import numpy as np
import osmnx as ox
import pandas as pd
import pyarrow.compute as pc
import pyarrow.dataset as ds
import requests
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, box, shape


MODULE_DIR = Path(__file__).resolve().parent

MICROSOFT_DATASET_LINKS = (
    "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
)
NSI_STRUCTURES_URL = "https://nsi.sec.usace.army.mil/nsiapi/structures?fmt=fc"
CENSUS_ACS_URL = "https://api.census.gov/data/{year}/acs/acs5"
ARCGIS_QUERY_PAGE_SIZE = 2000


STATE_FIPS = {}

STATE_ABBR_TO_NAME = {
    "AN": "Andaman and Nicobar Islands",
    "AP": "Andhra Pradesh",
    "AR": "Arunachal Pradesh",
    "AS": "Assam",
    "BR": "Bihar",
    "CG": "Chhattisgarh",
    "CH": "Chandigarh",
    "CT": "Chhattisgarh",
    "DD": "Dadra and Nagar Haveli and Daman and Diu",
    "DL": "Delhi",
    "DN": "Dadra and Nagar Haveli and Daman and Diu",
    "GA": "Goa",
    "GJ": "Gujarat",
    "HP": "Himachal Pradesh",
    "HR": "Haryana",
    "JH": "Jharkhand",
    "JK": "Jammu and Kashmir",
    "KA": "Karnataka",
    "KL": "Kerala",
    "LA": "Ladakh",
    "LD": "Lakshadweep",
    "MH": "Maharashtra",
    "ML": "Meghalaya",
    "MN": "Manipur",
    "MP": "Madhya Pradesh",
    "MZ": "Mizoram",
    "NL": "Nagaland",
    "OD": "Odisha",
    "OR": "Odisha",
    "PB": "Punjab",
    "PY": "Puducherry",
    "RJ": "Rajasthan",
    "SK": "Sikkim",
    "TG": "Telangana",
    "TN": "Tamil Nadu",
    "TR": "Tripura",
    "TS": "Telangana",
    "UK": "Uttarakhand",
    "UP": "Uttar Pradesh",
    "UT": "Uttarakhand",
    "WB": "West Bengal",
}

PARCEL_FIELD_ALIASES = {
    "ParcelID": [
        "parcel_id",
        "parcelid",
        "parcel_id",
        "parcel",
        "parid",
        "apn",
        "pin",
        "pid",
        "prop_id",
        "propid",
        "property_id",
        "account",
        "acct",
        "tax_id",
        "geoid",
        "objectid",
    ],
    "ParcelAddress": [
        "site_address",
        "situs_address",
        "situsaddr",
        "property_address",
        "address",
        "addr",
        "full_address",
        "location",
    ],
    "ParcelLandUse": [
        "land_use",
        "landuse",
        "use_code",
        "use_desc",
        "property_use",
        "prop_use",
        "class",
        "class_desc",
    ],
    "ParcelZoning": ["zoning", "zone", "zone_code", "zone_desc", "zoning_code"],
    "ParcelOwner": ["owner", "owner_name", "ownername", "taxpayer", "taxpayer_name"],
    "ParcelAssessedValue": [
        "assessed_value",
        "assessed",
        "total_value",
        "market_value",
        "appraised_value",
        "land_value",
        "improvement_value",
        "total_appraisal",
    ],
    "ParcelYearBuilt": ["year_built", "yr_built", "built_year", "yearbuilt", "yrbuilt"],
}

PARCEL_TEXT_COLUMNS = {
    "ParcelID",
    "ParcelAddress",
    "ParcelLandUse",
    "ParcelZoning",
    "ParcelOwner",
    "ParcelSource",
    "ParcelMatchMethod",
}

OUTPUT_COLUMNS = [
    "StructureID",
    "City",
    "State",
    "Country",
    "FootprintSource",
    "OvertureID",
    "MicrosoftID",
    "OSMID",
    "NSI_FD_ID",
    "NSI_RecordCount",
    "StructureType",
    "StructureTypeRaw",
    "StructureTypeSource",
    "BuildingName",
    "BuildingNameSource",
    "NumUnits",
    "NumUnitsSource",
    "NumStories",
    "NumStoriesSource",
    "HeightM",
    "HeightSource",
    "OccupantCount",
    "OccupantCountMethod",
    "NSI_Pop2AM",
    "NSI_Pop2PM",
    "NSI_EmpNum",
    "NSI_Students",
    "CBFIPS",
    "ParcelID",
    "ParcelAddress",
    "ParcelLandUse",
    "ParcelZoning",
    "ParcelOwner",
    "ParcelAssessedValue",
    "ParcelYearBuilt",
    "ParcelArea_m2",
    "ParcelSource",
    "ParcelMatchMethod",
    "FootprintArea_m2",
    "Confidence_MS",
    "HasParts",
    "CensusAvgHouseholdSize",
    "CensusSource",
    "geometry",
]


@dataclass
class PipelineConfig:
    data_dir: Path = field(default_factory=lambda: MODULE_DIR / "data")
    output_dir: Path = field(default_factory=lambda: MODULE_DIR / "data/output")
    raw_dir: Path = field(default_factory=lambda: MODULE_DIR / "data/raw")
    cache_dir: Path = field(default_factory=lambda: MODULE_DIR / "cache")
    country: str = "India"
    download_missing: bool = True
    use_overture: bool = True
    use_microsoft: bool = True
    use_osm: bool = True
    use_nsi: bool = False
    use_census: bool = False
    use_parcels: bool = True
    add_microsoft_unmatched: bool = True
    add_osm_unmatched: bool = True
    overture_release: str | None = None
    nsi_tile_size_deg: float = 0.08
    request_timeout_sec: int = 90
    microsoft_zoom: int = 9
    parcel_sources: dict[str, dict] = field(default_factory=dict)
    cache_remote_parcels: bool = True
    strict_sources: bool = False
    fail_on_empty_output: bool = False
    write_run_metadata: bool = True
    generic_microsoft_cache_slugs: set[str] = field(
        default_factory=set
    )

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.output_dir = Path(self.output_dir)
        self.raw_dir = Path(self.raw_dir)
        self.cache_dir = Path(self.cache_dir)
        self.generic_microsoft_cache_slugs = set(self.generic_microsoft_cache_slugs)
        self.parcel_sources = dict(self.parcel_sources)
        self.validate()

    def validate(self) -> None:
        if not str(self.country).strip():
            raise ValueError("country must not be empty")
        if self.request_timeout_sec <= 0:
            raise ValueError("request_timeout_sec must be positive")
        if self.nsi_tile_size_deg <= 0:
            raise ValueError("nsi_tile_size_deg must be positive")
        if not 0 < int(self.microsoft_zoom) <= 23:
            raise ValueError("microsoft_zoom must be between 1 and 23")

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.output_dir, self.raw_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)


def slugify(*parts: str) -> str:
    text = "_".join(str(part) for part in parts if part)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "place"


def normalize_state_name(state: str) -> str:
    stripped = state.strip()
    alias_key = re.sub(r"[^A-Za-z0-9]+", "", stripped).upper()
    if alias_key in STATE_ABBR_TO_NAME:
        return STATE_ABBR_TO_NAME[alias_key]
    return stripped


def to_numeric_safe(series: pd.Series | None, index=None) -> pd.Series:
    if series is None:
        return pd.Series(np.nan, index=index, dtype="float64")
    return pd.to_numeric(series, errors="coerce")


def parse_height_meters(series: pd.Series | None, index=None) -> pd.Series:
    if series is None:
        return pd.Series(np.nan, index=index, dtype="float64")

    def _parse(value):
        if pd.isna(value):
            return np.nan

        text = str(value).strip().lower()
        try:
            return float(text)
        except ValueError:
            pass

        match = re.match(r"([0-9.]+)\s*(m|meter|meters|ft|feet|')?", text)
        if not match:
            return np.nan

        number = float(match.group(1))
        unit = match.group(2)
        if unit in {"ft", "feet", "'"}:
            number *= 0.3048
        return number

    return series.apply(_parse)


def empty_gdf(columns: Iterable[str] = (), crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    data = {column: [] for column in columns if column != "geometry"}
    return gpd.GeoDataFrame(data, geometry=[], crs=crs)


def polygonal_part(geometry):
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type == "Polygon":
        return geometry
    if geometry.geom_type == "MultiPolygon":
        return geometry
    if geometry.geom_type != "GeometryCollection":
        return None

    polygons = []
    for part in geometry.geoms:
        polygonal = polygonal_part(part)
        if polygonal is None:
            continue
        if polygonal.geom_type == "Polygon":
            polygons.append(polygonal)
        else:
            polygons.extend(polygonal.geoms)

    if not polygons:
        return None
    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


def clean_geom(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    polygon_types = {"Polygon", "MultiPolygon"}
    geometry_column = gdf.geometry.name
    cleaned = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if cleaned.empty:
        return cleaned

    invalid = ~cleaned.geometry.is_valid
    if invalid.any():
        cleaned.loc[invalid, geometry_column] = cleaned.loc[
            invalid, geometry_column
        ].make_valid()

    cleaned[geometry_column] = cleaned.geometry.apply(polygonal_part)
    cleaned = cleaned[
        cleaned.geometry.notna()
        & ~cleaned.geometry.is_empty
        & cleaned.geometry.is_valid
        & cleaned.geometry.geom_type.isin(polygon_types)
    ].copy()
    return cleaned


def set_geometry_precision(
    gdf: gpd.GeoDataFrame, grid_size: float = 1e-9
) -> gpd.GeoDataFrame:
    precise = gdf.copy()
    precise[precise.geometry.name] = precise.geometry.set_precision(grid_size)
    return clean_geom(precise)


def clip_to_boundary(
    gdf: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    gdf = clean_geom(gdf)
    boundary = clean_geom(boundary)
    if gdf.empty or boundary.empty:
        return gdf.iloc[0:0].copy()
    gdf = clean_geom(gdf.to_crs(boundary.crs))
    if gdf.empty:
        return gdf
    try:
        clipped = gpd.clip(gdf, boundary)
    except GEOSException:
        clipped = gpd.clip(
            set_geometry_precision(gdf),
            set_geometry_precision(boundary),
        )
    return clean_geom(clipped).reset_index(drop=True)


def get_city_boundary(
    city: str, state: str, country: str = "India"
) -> gpd.GeoDataFrame:
    place = f"{city}, {normalize_state_name(state)}, {country}"
    boundary = ox.geocode_to_gdf(place).to_crs(epsg=4326)
    if len(boundary) > 1:
        unioned = (
            boundary.geometry.union_all()
            if hasattr(boundary.geometry, "union_all")
            else boundary.geometry.unary_union
        )
        boundary = gpd.GeoDataFrame(geometry=[unioned], crs=4326)
    return boundary[["geometry"]].reset_index(drop=True)


def bounds_tuple(boundary: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = boundary.total_bounds
    return float(minx), float(miny), float(maxx), float(maxy)


def resolve_source_path(path_value: str | Path, config: PipelineConfig | None = None) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path

    candidates = []
    if config is not None:
        if len(path.parts) == 1:
            candidates.append(config.raw_dir / path)
        candidates.append(config.data_dir.parent / path)
    candidates.append(path)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[1] if config is not None and len(candidates) > 1 else path


def source_failure(
    message: str, config: PipelineConfig | None = None, exc: Exception | None = None
) -> None:
    if config is not None and config.strict_sources:
        raise RuntimeError(message) from exc
    print(message)


def json_safe(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(json_safe(item) for item in value)
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, np.generic):
        return value.item()
    if not isinstance(value, (list, dict, set, tuple)):
        try:
            missing = pd.isna(value)
            if isinstance(missing, (bool, np.bool_)) and missing:
                return None
        except TypeError:
            pass
    return value


def config_metadata(config: PipelineConfig) -> dict:
    return {field.name: json_safe(getattr(config, field.name)) for field in fields(config)}


def write_metadata_sidecar(
    output_path: Path, config: PipelineConfig, metadata: dict
) -> None:
    if not config.write_run_metadata:
        return
    sidecar_path = Path(f"{output_path}.metadata.json")
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }
    sidecar_path.write_text(json.dumps(json_safe(payload), indent=2))


def validate_output_gdf(
    gdf: gpd.GeoDataFrame, dataset_name: str, config: PipelineConfig
) -> None:
    if gdf.empty:
        if config.fail_on_empty_output:
            raise ValueError(f"{dataset_name} output is empty")
        return
    if gdf.crs is None:
        raise ValueError(f"{dataset_name} output has no CRS")
    if "StructureID" not in gdf.columns:
        raise ValueError(f"{dataset_name} output is missing StructureID")
    if gdf["StructureID"].isna().any():
        raise ValueError(f"{dataset_name} output has null StructureID values")
    duplicate_count = int(gdf["StructureID"].duplicated().sum())
    if duplicate_count:
        raise ValueError(
            f"{dataset_name} output has {duplicate_count:,} duplicate StructureID values"
        )
    if gdf.geometry.isna().any():
        raise ValueError(f"{dataset_name} output has null geometries")
    if (~gdf.geometry.is_valid).any():
        raise ValueError(f"{dataset_name} output has invalid geometries")


def bbox_covers(outer: dict, bounds: tuple[float, float, float, float]) -> bool:
    minx, miny, maxx, maxy = bounds
    return (
        outer["xmin"] <= minx
        and outer["ymin"] <= miny
        and outer["xmax"] >= maxx
        and outer["ymax"] >= maxy
    )


def state_file_covers(path: Path, bounds: tuple[float, float, float, float]) -> bool:
    state_path = Path(f"{path}.state")
    if not state_path.exists():
        return False
    try:
        state = json.loads(state_path.read_text())
        return bbox_covers(state["bbox"], bounds)
    except Exception:
        return False


def read_overture_parquet(
    path: Path, boundary: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    if not path.exists():
        return empty_gdf(
            [
                "OvertureID",
                "BuildingName_OVT",
                "Height_OVT",
                "Stories_OVT",
                "OvertureSubtype",
                "OvertureClass",
                "HasParts",
            ]
        )

    minx, miny, maxx, maxy = bounds_tuple(boundary)
    dataset = ds.dataset(path, format="parquet")
    schema_names = set(dataset.schema.names)
    columns = [
        column
        for column in [
            "id",
            "names",
            "height",
            "num_floors",
            "subtype",
            "class",
            "has_parts",
            "geometry",
        ]
        if column in schema_names
    ]

    filter_expr = None
    if "bbox" in schema_names:
        filter_expr = (
            (pc.field("bbox", "xmin") <= maxx)
            & (pc.field("bbox", "xmax") >= minx)
            & (pc.field("bbox", "ymin") <= maxy)
            & (pc.field("bbox", "ymax") >= miny)
        )

    table = dataset.to_table(columns=columns, filter=filter_expr)
    if table.num_rows == 0:
        return empty_gdf()

    df = table.to_pandas()
    geometry = gpd.GeoSeries.from_wkb(df.pop("geometry"), crs="EPSG:4326")
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
    gdf = clip_to_boundary(gdf, boundary)
    if gdf.empty:
        return empty_gdf()

    names = gdf.get("names")
    if names is None:
        building_names = pd.Series(pd.NA, index=gdf.index)
    else:
        building_names = names.apply(
            lambda value: value.get("primary")
            if isinstance(value, dict) and value.get("primary")
            else pd.NA
        )

    out = gpd.GeoDataFrame(
        {
            "StructureID": "ovt_" + gdf.get("id", pd.Series(gdf.index)).astype(str),
            "FootprintSource": "overture",
            "OvertureID": gdf.get("id", pd.Series(pd.NA, index=gdf.index)).astype(
                "string"
            ),
            "MicrosoftID": pd.Series(pd.NA, index=gdf.index, dtype="string"),
            "BuildingName_OVT": building_names,
            "Height_OVT": to_numeric_safe(gdf.get("height"), index=gdf.index),
            "Stories_OVT": to_numeric_safe(gdf.get("num_floors"), index=gdf.index),
            "OvertureSubtype": gdf.get("subtype", pd.Series(pd.NA, index=gdf.index)),
            "OvertureClass": gdf.get("class", pd.Series(pd.NA, index=gdf.index)),
            "HasParts": gdf.get("has_parts", pd.Series(pd.NA, index=gdf.index)),
            "Height_MS": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "Confidence_MS": pd.Series(np.nan, index=gdf.index, dtype="float64"),
        },
        geometry=gdf.geometry,
        crs=gdf.crs,
    )
    return out.reset_index(drop=True)


def overture_city_path(
    city_slug: str, bounds: tuple[float, float, float, float], config: PipelineConfig
) -> Path | None:
    city_path = config.raw_dir / f"overture_{city_slug}.parquet"
    if city_path.exists():
        return city_path

    generic_path = config.data_dir / "overture_buildings.parquet"
    if generic_path.exists() and state_file_covers(generic_path, bounds):
        return generic_path

    if not config.download_missing:
        return None

    try:
        download_overture_buildings(bounds, city_path, config)
    except Exception as exc:
        print(f"Overture source skipped: download failed: {exc}")
        return None
    return city_path


def download_overture_buildings(
    bounds: tuple[float, float, float, float], output_path: Path, config: PipelineConfig
) -> None:
    exe = shutil.which("overturemaps")
    if exe is None:
        candidate = Path(sys.executable).parent / "overturemaps"
        exe = str(candidate) if candidate.exists() else None
    if exe is None:
        raise RuntimeError(
            "overturemaps is not installed. Install requirements.txt or set download_missing=False."
        )

    bbox = ",".join(f"{value:.8f}" for value in bounds)
    cmd = [
        exe,
        "download",
        f"--bbox={bbox}",
        "-f",
        "geoparquet",
        "-t",
        "building",
        "-o",
        str(output_path),
    ]
    if config.overture_release:
        cmd.extend(["--release", config.overture_release])

    print(f"Downloading Overture buildings to {output_path}")
    env = os.environ.copy()
    ca_bundle = certifi.where()
    env.setdefault("SSL_CERT_FILE", ca_bundle)
    env.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)

    completed = subprocess.run(
        cmd,
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        output_path.unlink(missing_ok=True)
        Path(f"{output_path}.state").unlink(missing_ok=True)
        details = "\n".join(
            part.strip()
            for part in [completed.stderr, completed.stdout]
            if part and part.strip()
        )
        raise RuntimeError(details or f"overturemaps exited {completed.returncode}")
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip())

    state = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "release": config.overture_release or "latest",
        "type": "building",
        "bbox": {
            "xmin": bounds[0],
            "ymin": bounds[1],
            "xmax": bounds[2],
            "ymax": bounds[3],
        },
        "output": str(output_path),
    }
    Path(f"{output_path}.state").write_text(json.dumps(state, indent=2))


def load_overture_buildings(
    city_slug: str, boundary: gpd.GeoDataFrame, config: PipelineConfig
) -> gpd.GeoDataFrame:
    if not config.use_overture:
        return empty_gdf()
    path = overture_city_path(city_slug, bounds_tuple(boundary), config)
    if path is None:
        print("Overture source skipped: no local file and download_missing=False")
        return empty_gdf()
    return read_overture_parquet(path, boundary)


def read_remote_csv(url: str, **kwargs) -> pd.DataFrame:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(url, context=ssl_context) as response:
        return pd.read_csv(response, **kwargs)


def read_remote_json_lines(url: str) -> pd.DataFrame:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(url, context=ssl_context) as response:
        if url.split("?", 1)[0].endswith(".gz"):
            with gzip.GzipFile(fileobj=response) as decompressed:
                return pd.read_json(decompressed, lines=True)
        return pd.read_json(response, lines=True)


def quadkeys_for_bounds(
    bounds: tuple[float, float, float, float], zoom: int
) -> list[str]:
    minx, miny, maxx, maxy = bounds
    return sorted(
        {
            mercantile.quadkey(tile)
            for tile in mercantile.tiles(minx, miny, maxx, maxy, zooms=[zoom])
        }
    )


def read_microsoft_tile(url: str) -> gpd.GeoDataFrame:
    df = read_remote_json_lines(url)
    if "properties" in df.columns:
        properties = pd.json_normalize(df["properties"]).set_index(df.index)
        df = pd.concat([df.drop(columns=["properties"]), properties], axis=1)
    df["geometry"] = df["geometry"].apply(
        lambda geometry: shape(geometry) if isinstance(geometry, dict) else geometry
    )
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    keep = [column for column in ["height", "confidence", "geometry"] if column in gdf]
    return gdf[keep]


def download_microsoft_buildings(
    boundary: gpd.GeoDataFrame, output_path: Path, config: PipelineConfig
) -> gpd.GeoDataFrame:
    bounds = bounds_tuple(boundary)
    quad_keys = quadkeys_for_bounds(bounds, zoom=config.microsoft_zoom)
    links = read_remote_csv(MICROSOFT_DATASET_LINKS, dtype=str)
    pieces: list[gpd.GeoDataFrame] = []

    print(f"Downloading Microsoft buildings for {len(quad_keys)} quadkeys")
    for quad_key in quad_keys:
        rows = links[links["QuadKey"] == quad_key]
        if rows.empty:
            continue
        for url in rows["Url"].dropna().unique():
            tile = read_microsoft_tile(url)
            if tile.empty:
                continue
            minx, miny, maxx, maxy = bounds
            tile = tile.cx[minx:maxx, miny:maxy]
            tile = clip_to_boundary(tile, boundary)
            if not tile.empty:
                pieces.append(tile)

    if not pieces:
        print("Microsoft source returned no polygons")
        return empty_gdf()

    microsoft = gpd.GeoDataFrame(
        pd.concat(pieces, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )
    microsoft = clean_geom(microsoft)
    microsoft.to_parquet(output_path, index=False)
    Path(f"{output_path}.state").write_text(
        json.dumps(
            {
                "last_run": datetime.now(timezone.utc).isoformat(),
                "bbox": {
                    "xmin": bounds[0],
                    "ymin": bounds[1],
                    "xmax": bounds[2],
                    "ymax": bounds[3],
                },
                "output": str(output_path),
            },
            indent=2,
        )
    )
    return microsoft


def standardize_microsoft(
    gdf: gpd.GeoDataFrame, city_slug: str
) -> gpd.GeoDataFrame:
    if gdf.empty:
        return empty_gdf()
    gdf = clean_geom(gdf.to_crs(epsg=4326)).reset_index(drop=True)
    index = pd.Series(gdf.index, index=gdf.index).astype(str)
    out = gpd.GeoDataFrame(
        {
            "StructureID": f"msft_{city_slug}_" + index,
            "FootprintSource": "microsoft",
            "OvertureID": pd.Series(pd.NA, index=gdf.index, dtype="string"),
            "MicrosoftID": f"msft_{city_slug}_" + index,
            "BuildingName_OVT": pd.Series(pd.NA, index=gdf.index),
            "Height_OVT": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "Stories_OVT": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "OvertureSubtype": pd.Series(pd.NA, index=gdf.index),
            "OvertureClass": pd.Series(pd.NA, index=gdf.index),
            "HasParts": pd.Series(False, index=gdf.index),
            "Height_MS": to_numeric_safe(gdf.get("height"), index=gdf.index).replace(
                -1, np.nan
            ),
            "Confidence_MS": to_numeric_safe(
                gdf.get("confidence"), index=gdf.index
            ).replace(-1, np.nan),
        },
        geometry=gdf.geometry,
        crs=gdf.crs,
    )
    return out.reset_index(drop=True)


def load_microsoft_buildings(
    city_slug: str, boundary: gpd.GeoDataFrame, config: PipelineConfig
) -> gpd.GeoDataFrame:
    if not config.use_microsoft:
        return empty_gdf()

    city_path = config.raw_dir / f"microsoft_{city_slug}.parquet"
    if city_path.exists():
        return standardize_microsoft(gpd.read_parquet(city_path), city_slug)

    generic_path = config.data_dir / "microsoft_buildings.parquet"
    if city_slug in config.generic_microsoft_cache_slugs and generic_path.exists():
        generic = gpd.read_parquet(generic_path)
        generic = clip_to_boundary(generic, boundary)
        if not generic.empty:
            return standardize_microsoft(generic, city_slug)

    if not config.download_missing:
        print("Microsoft source skipped: no local city file and download_missing=False")
        return empty_gdf()

    microsoft = download_microsoft_buildings(boundary, city_path, config)
    return standardize_microsoft(microsoft, city_slug)


def merge_footprints(
    overture: gpd.GeoDataFrame,
    microsoft: gpd.GeoDataFrame,
    config: PipelineConfig,
) -> gpd.GeoDataFrame:
    if overture.empty and microsoft.empty:
        return empty_gdf()
    if overture.empty:
        return microsoft.reset_index(drop=True)
    if microsoft.empty or not config.add_microsoft_unmatched:
        return overture.reset_index(drop=True)

    points = microsoft[["StructureID", "geometry"]].copy()
    points["geometry"] = points.geometry.representative_point()
    matched = gpd.sjoin(
        points,
        overture[["StructureID", "geometry"]].rename(
            columns={"StructureID": "OvertureStructureID"}
        ),
        how="left",
        predicate="within",
    )
    unmatched_ids = matched.loc[
        matched["OvertureStructureID"].isna(), "StructureID"
    ].unique()
    microsoft_extra = microsoft[microsoft["StructureID"].isin(unmatched_ids)]
    merged = gpd.GeoDataFrame(
        pd.concat([overture, microsoft_extra], ignore_index=True),
        geometry="geometry",
        crs=overture.crs,
    )
    return merged.reset_index(drop=True)


def get_osm_buildings(
    boundary: gpd.GeoDataFrame, config: PipelineConfig
) -> gpd.GeoDataFrame:
    if not config.use_osm:
        return empty_gdf()
    try:
        polygon = boundary.geometry.iloc[0]
        raw = ox.features_from_polygon(polygon, tags={"building": True}).reset_index()
    except Exception as exc:
        print(f"OSM source skipped: {exc}")
        return empty_gdf()

    if raw.empty:
        return empty_gdf()
    raw = clean_geom(raw)
    if raw.empty:
        return empty_gdf()

    osmid = raw.get("osmid", raw.get("id", pd.Series(raw.index, index=raw.index)))
    units = to_numeric_safe(raw.get("building:flats"), index=raw.index)
    for column in ("residential:units", "building:units", "units"):
        if column in raw.columns:
            units = units.combine_first(to_numeric_safe(raw[column], index=raw.index))

    structure_ids = ("osm_" + osmid.astype(str)).astype("string")
    duplicate_mask = structure_ids.duplicated(keep=False)
    if duplicate_mask.any():
        duplicate_order = structure_ids.groupby(structure_ids).cumcount()
        structure_ids = structure_ids.where(
            ~duplicate_mask,
            structure_ids + "_" + duplicate_order.astype(str),
        )

    out = gpd.GeoDataFrame(
        {
            "StructureID": structure_ids,
            "FootprintSource": "osm",
            "OvertureID": pd.Series(pd.NA, index=raw.index, dtype="string"),
            "MicrosoftID": pd.Series(pd.NA, index=raw.index, dtype="string"),
            "Confidence_MS": pd.Series(np.nan, index=raw.index),
            "HasParts": pd.Series(False, index=raw.index),
            "OSMID": osmid.astype("string"),
            "OSM_StructureType": raw.get(
                "building", pd.Series(pd.NA, index=raw.index)
            ),
            "Stories_OSM": to_numeric_safe(raw.get("building:levels"), index=raw.index),
            "Height_OSM": parse_height_meters(raw.get("height"), index=raw.index),
            "Units_OSM": units,
            "BuildingName_OSM": raw.get("name", pd.Series(pd.NA, index=raw.index)),
        },
        geometry=raw.geometry,
        crs=raw.crs,
    )
    return out.to_crs(epsg=4326).reset_index(drop=True)


def merge_osm_footprints(
    base: gpd.GeoDataFrame,
    osm: gpd.GeoDataFrame,
    config: PipelineConfig,
) -> gpd.GeoDataFrame:
    if osm.empty:
        return base
    if base.empty:
        return osm.reset_index(drop=True)
    if not config.add_osm_unmatched:
        return base

    points = osm[["StructureID", "geometry"]].copy()
    points["geometry"] = points.geometry.representative_point()
    matched = gpd.sjoin(
        points,
        base[["StructureID", "geometry"]].rename(columns={"StructureID": "BaseStructureID"}),
        how="left",
        predicate="within",
    )
    unmatched_ids = matched.loc[matched["BaseStructureID"].isna(), "StructureID"].unique()
    if len(unmatched_ids) == 0:
        return base

    osm_extra = osm[osm["StructureID"].isin(unmatched_ids)]
    merged = gpd.GeoDataFrame(
        pd.concat([base, osm_extra], ignore_index=True),
        geometry="geometry",
        crs=base.crs,
    )
    return merged.reset_index(drop=True)


def attach_osm_attributes(
    base: gpd.GeoDataFrame, osm: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    if base.empty:
        return base
    osm_columns = [
        "OSMID",
        "OSM_StructureType",
        "Stories_OSM",
        "Height_OSM",
        "Units_OSM",
        "BuildingName_OSM",
    ]
    for column in osm_columns:
        if column not in base.columns:
            numeric_column = column in {"Stories_OSM", "Height_OSM", "Units_OSM"}
            base[column] = np.nan if numeric_column else pd.NA

    if osm.empty:
        return base

    points = base[["StructureID", "geometry"]].copy()
    points["geometry"] = points.geometry.representative_point()
    joined = gpd.sjoin(
        points,
        osm[osm_columns + ["geometry"]],
        how="left",
        predicate="within",
    )
    joined = joined.drop_duplicates("StructureID").set_index("StructureID")
    base = base.set_index("StructureID")
    for column in osm_columns:
        base[column] = joined[column].reindex(base.index).combine_first(base[column])
    return base.reset_index()


def iter_boundary_tiles(
    boundary: gpd.GeoDataFrame, step_deg: float
) -> Iterable[gpd.GeoDataFrame]:
    minx, miny, maxx, maxy = bounds_tuple(boundary)
    x_count = max(1, math.ceil((maxx - minx) / step_deg))
    y_count = max(1, math.ceil((maxy - miny) / step_deg))
    polygon = boundary.geometry.iloc[0]
    for ix in range(x_count):
        x0 = minx + ix * step_deg
        x1 = min(maxx, x0 + step_deg)
        for iy in range(y_count):
            y0 = miny + iy * step_deg
            y1 = min(maxy, y0 + step_deg)
            tile_geom = box(x0, y0, x1, y1)
            if not tile_geom.intersects(polygon):
                continue
            yield gpd.GeoDataFrame(geometry=[tile_geom], crs=boundary.crs)


def get_nsi_structures(
    boundary: gpd.GeoDataFrame, config: PipelineConfig
) -> gpd.GeoDataFrame:
    if not config.use_nsi:
        return empty_gdf()
    if config.country.strip().lower() not in {"usa", "united states", "united states of america"}:
        print("NSI source skipped: NSI is only configured for U.S. locations")
        return empty_gdf()

    session = requests.Session()
    pieces = []
    seen_ids: set[str] = set()
    for tile in iter_boundary_tiles(boundary, config.nsi_tile_size_deg):
        body = json.loads(tile.to_json())
        try:
            response = session.post(
                NSI_STRUCTURES_URL,
                json=body,
                timeout=config.request_timeout_sec,
                verify=certifi.where(),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            print(f"NSI tile skipped: {exc}")
            continue

        features = payload.get("features", [])
        if not features:
            continue
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        if "fd_id" in gdf.columns:
            ids = gdf["fd_id"].astype(str)
            keep = ~ids.isin(seen_ids)
            seen_ids.update(ids[keep].tolist())
            gdf = gdf.loc[keep]
        pieces.append(gdf)

    if not pieces:
        return empty_gdf()

    nsi = gpd.GeoDataFrame(
        pd.concat(pieces, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )
    nsi = nsi[nsi.geometry.notna()].copy()
    nsi = nsi[nsi.geometry.within(boundary.geometry.iloc[0])].reset_index(drop=True)
    return nsi


def mode_value(series: pd.Series):
    values = series.dropna()
    if values.empty:
        return pd.NA
    mode = values.mode()
    return mode.iloc[0] if not mode.empty else values.iloc[0]


def first_value(series: pd.Series):
    values = series.dropna()
    return values.iloc[0] if not values.empty else pd.NA


def sum_min_count(series: pd.Series):
    return series.sum(min_count=1)


def attach_nsi_attributes(
    base: gpd.GeoDataFrame, nsi: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    columns = [
        "NSI_FD_ID",
        "NSI_RecordCount",
        "NSI_OccType",
        "NSI_DamageCategory",
        "CBFIPS",
        "NSI_NumStory",
        "NSI_ResUnits",
        "NSI_EmpNum",
        "NSI_Students",
        "NSI_Sqft",
        "NSI_Pop2AM",
        "NSI_Pop2PM",
        "NSI_ValStruct",
    ]
    for column in columns:
        if column not in base.columns:
            text_column = column in {
                "NSI_FD_ID",
                "NSI_OccType",
                "NSI_DamageCategory",
                "CBFIPS",
            }
            base[column] = pd.NA if text_column else np.nan
    if base.empty or nsi.empty:
        return base

    fields = [
        "fd_id",
        "occtype",
        "st_damcat",
        "cbfips",
        "num_story",
        "resunits",
        "empnum",
        "students",
        "sqft",
        "pop2amu65",
        "pop2amo65",
        "pop2pmu65",
        "pop2pmo65",
        "val_struct",
        "geometry",
    ]
    for field_name in fields:
        if field_name not in nsi.columns and field_name != "geometry":
            nsi[field_name] = np.nan

    nsi = nsi[fields].copy()
    for numeric in [
        "num_story",
        "resunits",
        "empnum",
        "students",
        "sqft",
        "pop2amu65",
        "pop2amo65",
        "pop2pmu65",
        "pop2pmo65",
        "val_struct",
    ]:
        nsi[numeric] = to_numeric_safe(nsi[numeric], index=nsi.index)

    nsi["NSI_Pop2AM"] = nsi[["pop2amu65", "pop2amo65"]].sum(
        axis=1, min_count=1
    )
    nsi["NSI_Pop2PM"] = nsi[["pop2pmu65", "pop2pmo65"]].sum(
        axis=1, min_count=1
    )
    joined = gpd.sjoin(
        nsi,
        base[["StructureID", "geometry"]],
        how="inner",
        predicate="within",
    )
    if joined.empty:
        return base

    aggregated = joined.groupby("StructureID").agg(
        NSI_FD_ID=("fd_id", first_value),
        NSI_RecordCount=("fd_id", "count"),
        NSI_OccType=("occtype", mode_value),
        NSI_DamageCategory=("st_damcat", mode_value),
        CBFIPS=("cbfips", mode_value),
        NSI_NumStory=("num_story", "median"),
        NSI_ResUnits=("resunits", sum_min_count),
        NSI_EmpNum=("empnum", sum_min_count),
        NSI_Students=("students", sum_min_count),
        NSI_Sqft=("sqft", sum_min_count),
        NSI_Pop2AM=("NSI_Pop2AM", sum_min_count),
        NSI_Pop2PM=("NSI_Pop2PM", sum_min_count),
        NSI_ValStruct=("val_struct", sum_min_count),
    )

    base = base.set_index("StructureID")
    for column in aggregated.columns:
        base[column] = aggregated[column].reindex(base.index).combine_first(base[column])
    return base.reset_index()


def normalized_place_name(name: str) -> str:
    text = name.split(",", 1)[0].lower()
    text = re.sub(r"\b(city|town|village|borough|municipality|cdp)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text


def get_census_household_size(
    city: str, state: str, config: PipelineConfig
) -> tuple[float | None, str | None]:
    if not config.use_census:
        return None, None
    if config.country.strip().lower() not in {"usa", "united states", "united states of america"}:
        print("Census source skipped: ACS Census lookup is only configured for U.S. locations")
        return None, None

    state_name = normalize_state_name(state)
    fips = STATE_FIPS.get(state_name.lower())
    if not fips:
        print(f"Census source skipped: unknown state {state}")
        return None, None

    target = normalized_place_name(city)
    session = requests.Session()
    for year in (2024, 2023, 2022, 2021, 2020):
        params = {
            "get": "NAME,B25010_001E",
            "for": "place:*",
            "in": f"state:{fips}",
        }
        try:
            response = session.get(
                CENSUS_ACS_URL.format(year=year),
                params=params,
                timeout=config.request_timeout_sec,
                verify=certifi.where(),
            )
            response.raise_for_status()
            rows = response.json()
        except Exception:
            continue

        if not rows or len(rows) < 2:
            continue
        header = rows[0]
        name_i = header.index("NAME")
        value_i = header.index("B25010_001E")
        for row in rows[1:]:
            if normalized_place_name(row[name_i]) == target:
                value = pd.to_numeric(row[value_i], errors="coerce")
                if pd.notna(value) and value > 0:
                    return float(value), f"ACS {year} B25010_001E"

    print("Census household size not found; residential occupancy fallback disabled")
    return None, None


def combine_first_with_source(
    df: pd.DataFrame, choices: list[tuple[str, str]]
) -> tuple[pd.Series, pd.Series]:
    values = pd.Series(pd.NA, index=df.index, dtype="object")
    sources = pd.Series(pd.NA, index=df.index, dtype="object")
    for column, source in choices:
        if column not in df.columns:
            continue
        candidate = df[column]
        mask = values.isna() & candidate.notna()
        if candidate.dtype == object or str(candidate.dtype).startswith("string"):
            mask &= candidate.astype(str).str.strip().ne("")
        values.loc[mask] = candidate.loc[mask]
        sources.loc[mask] = source
    return values, sources


def normalize_structure_type(raw: pd.Series) -> pd.Series:
    text = raw.fillna("").astype(str).str.lower()
    result = pd.Series("unknown", index=raw.index, dtype="object")

    rules = [
        (r"condo|condominium", "condo"),
        (r"apart|res3|multi.?family|multifamily", "apartment"),
        (r"hotel|motel|res4", "hotel"),
        (r"garage|garages|parking", "garage"),
        (r"barn|farm_auxiliary|agric|stable|greenhouse", "barn"),
        (r"mobile|res2|manufactured", "mobile_home"),
        (r"school|college|university|edu", "education"),
        (r"hospital|clinic|medical|nursing|res6", "healthcare"),
        (r"warehouse|wholesale|com2", "warehouse"),
        (r"industrial|factory|ind", "industrial"),
        (r"retail|office|commercial|com", "commercial"),
        (r"church|civic|public|government|religious", "public"),
        (r"house|detached|semidetached|terrace|residential|res1|res", "residential"),
    ]
    for pattern, label in rules:
        mask = result.eq("unknown") & text.str.contains(pattern, regex=True, na=False)
        result.loc[mask] = label
    return result


def add_area(base: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if base.empty:
        base["FootprintArea_m2"] = []
        return base
    projected_crs = base.estimate_utm_crs()
    if projected_crs is None:
        projected_crs = "EPSG:6933"
    base["FootprintArea_m2"] = base.to_crs(projected_crs).geometry.area.values
    return base


def normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def parcel_source_for_city(
    city_slug: str,
    city: str,
    state: str,
    country: str,
    config: PipelineConfig,
    parcel_source: dict | str | None = None,
) -> dict | None:
    source = parcel_source
    for key in (
        city_slug,
        slugify(city, state),
        slugify(city),
        f"{city}, {state}",
    ):
        if source is None and key in config.parcel_sources:
            source = config.parcel_sources[key]
    if source is None:
        return None
    if isinstance(source, str):
        return {"url": source} if source.lower().startswith("http") else {"path": source}
    return dict(source)


def find_source_column(
    gdf: gpd.GeoDataFrame, source: dict, canonical_name: str
) -> str | None:
    field_map = source.get("field_map", {})
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", canonical_name).lower()
    configured = (
        field_map.get(canonical_name)
        or field_map.get(snake)
        or source.get(canonical_name)
        or source.get(snake)
    )
    candidates = []
    if configured:
        candidates.extend(configured if isinstance(configured, list) else [configured])
    candidates.extend(PARCEL_FIELD_ALIASES[canonical_name])

    lookup = {normalize_field_name(column): column for column in gdf.columns}
    for candidate in candidates:
        column = lookup.get(normalize_field_name(candidate))
        if column:
            return column
    return None


def read_parcel_file(
    source: dict, boundary: gpd.GeoDataFrame, config: PipelineConfig
) -> gpd.GeoDataFrame:
    path = resolve_source_path(source["path"], config)
    if not path.exists():
        source_failure(f"Parcels skipped: file not found at {path}", config)
        return empty_gdf()

    suffix = path.suffix.lower()
    if suffix in {".parquet", ".geoparquet"}:
        parcels = gpd.read_parquet(path)
    else:
        try:
            parcels = gpd.read_file(path, bbox=bounds_tuple(boundary))
        except TypeError:
            parcels = gpd.read_file(path)
    if parcels.crs is None:
        source_crs = source.get("crs", "EPSG:4326")
        source_failure(f"Parcels file has no CRS; assuming {source_crs}", None)
        parcels = parcels.set_crs(source_crs)
    return clip_to_boundary(parcels, boundary)


def read_arcgis_parcels(
    source: dict, boundary: gpd.GeoDataFrame, config: PipelineConfig
) -> gpd.GeoDataFrame:
    url = source["url"].rstrip("/")
    query_url = url if url.endswith("/query") else f"{url}/query"
    minx, miny, maxx, maxy = bounds_tuple(boundary)
    geometry = {
        "xmin": minx,
        "ymin": miny,
        "xmax": maxx,
        "ymax": maxy,
        "spatialReference": {"wkid": 4326},
    }
    page_size = int(source.get("page_size", ARCGIS_QUERY_PAGE_SIZE))
    session = requests.Session()
    features = []
    offset = 0

    while True:
        params = {
            "f": "geojson",
            "where": source.get("where", "1=1"),
            "outFields": source.get("out_fields", "*"),
            "returnGeometry": "true",
            "geometry": json.dumps(geometry),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "outSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "resultRecordCount": page_size,
            "resultOffset": offset,
        }
        try:
            response = session.get(
                query_url,
                params=params,
                timeout=source.get("timeout", 120),
                verify=certifi.where(),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            source_failure(
                f"Parcels skipped: ArcGIS request failed for {url}: {exc}",
                config,
                exc,
            )
            return empty_gdf()

        batch = payload.get("features", [])
        if not batch:
            break
        features.extend(batch)
        offset += len(batch)
        if len(batch) < page_size and not payload.get("exceededTransferLimit"):
            break

    if not features:
        return empty_gdf()

    parcels = gpd.GeoDataFrame.from_features(
        {"type": "FeatureCollection", "features": features}, crs="EPSG:4326"
    )
    return clip_to_boundary(parcels, boundary)


def standardize_parcels(
    parcels: gpd.GeoDataFrame, source: dict, source_name: str
) -> gpd.GeoDataFrame:
    if parcels.empty:
        return empty_gdf()

    parcels = clean_geom(parcels.to_crs(epsg=4326)).reset_index(drop=True)
    values = {}
    for canonical_name in PARCEL_FIELD_ALIASES:
        source_column = find_source_column(parcels, source, canonical_name)
        if source_column:
            values[canonical_name] = parcels[source_column]
        elif canonical_name in PARCEL_TEXT_COLUMNS:
            values[canonical_name] = pd.Series(pd.NA, index=parcels.index)
        else:
            values[canonical_name] = pd.Series(np.nan, index=parcels.index)

    out = gpd.GeoDataFrame(values, geometry=parcels.geometry, crs=parcels.crs)
    out["ParcelSource"] = source_name
    out["ParcelAssessedValue"] = to_numeric_safe(
        out["ParcelAssessedValue"], index=out.index
    )
    out["ParcelYearBuilt"] = to_numeric_safe(out["ParcelYearBuilt"], index=out.index)

    projected_crs = out.estimate_utm_crs() or "EPSG:6933"
    out["ParcelArea_m2"] = out.to_crs(projected_crs).geometry.area.values
    return out.reset_index(drop=True)


def load_city_parcels(
    city_slug: str,
    city: str,
    state: str,
    boundary: gpd.GeoDataFrame,
    config: PipelineConfig,
    parcel_source: dict | str | None = None,
) -> gpd.GeoDataFrame:
    if not config.use_parcels:
        return empty_gdf()

    source = parcel_source_for_city(
        city_slug, city, state, config.country, config, parcel_source
    )
    if source is None:
        print("Parcels skipped: no parcel source configured for this city")
        return empty_gdf()

    cache_path = config.raw_dir / f"parcels_{city_slug}.parquet"
    if source.get("url") and config.cache_remote_parcels and cache_path.exists():
        return gpd.read_parquet(cache_path)

    source_name = source.get("name") or source.get("path") or source.get("url")
    if source.get("path"):
        raw = read_parcel_file(source, boundary, config)
    elif source.get("url"):
        raw = read_arcgis_parcels(source, boundary, config)
    else:
        source_failure(
            "Parcels skipped: source must include either 'path' or 'url'", config
        )
        return empty_gdf()

    parcels = standardize_parcels(raw, source, str(source_name))
    if source.get("url") and config.cache_remote_parcels and not parcels.empty:
        parcels.to_parquet(cache_path, index=False)
    return parcels


def attach_parcel_attributes(
    base: gpd.GeoDataFrame, parcels: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    parcel_columns = [
        "ParcelID",
        "ParcelAddress",
        "ParcelLandUse",
        "ParcelZoning",
        "ParcelOwner",
        "ParcelAssessedValue",
        "ParcelYearBuilt",
        "ParcelArea_m2",
        "ParcelSource",
        "ParcelMatchMethod",
    ]
    for column in parcel_columns:
        if column not in base.columns:
            base[column] = pd.NA if column in PARCEL_TEXT_COLUMNS else np.nan
    if base.empty or parcels.empty:
        return base

    points = base[["StructureID", "geometry"]].copy()
    points["geometry"] = points.geometry.representative_point()
    joined = gpd.sjoin(
        points,
        parcels[[column for column in parcel_columns if column in parcels] + ["geometry"]],
        how="left",
        predicate="within",
    )
    joined = joined.sort_values(
        ["StructureID", "ParcelArea_m2"], na_position="last"
    ).drop_duplicates("StructureID")
    joined = joined.set_index("StructureID")
    base = base.set_index("StructureID")
    for column in parcel_columns:
        if column == "ParcelMatchMethod":
            matched = joined.get("ParcelSource", pd.Series(index=joined.index)).notna()
            parcel_values = pd.Series(pd.NA, index=joined.index)
            parcel_values.loc[matched] = "representative_point_within"
        else:
            parcel_values = joined.get(column, pd.Series(index=joined.index))
        base[column] = parcel_values.reindex(base.index).combine_first(base[column])
    return base.reset_index()



def finalize_attributes(
    base: gpd.GeoDataFrame,
    city: str,
    state: str,
    country: str,
    census_household_size: float | None,
    census_source: str | None,
) -> gpd.GeoDataFrame:
    if base.empty:
        return empty_gdf(OUTPUT_COLUMNS)

    base = add_area(base.copy())
    base["City"] = city
    base["State"] = normalize_state_name(state)
    base["Country"] = country

    base["BuildingName"], base["BuildingNameSource"] = combine_first_with_source(
        base,
        [
            ("BuildingName_OSM", "osm"),
            ("BuildingName_OVT", "overture"),
        ],
    )
    base["StructureTypeRaw"], base["StructureTypeSource"] = combine_first_with_source(
        base,
        [
            ("OSM_StructureType", "osm"),
            ("OvertureClass", "overture_class"),
            ("OvertureSubtype", "overture_subtype"),
            ("NSI_OccType", "nsi_occtype"),
            ("NSI_DamageCategory", "nsi_damage_category"),
        ],
    )
    base["StructureType"] = normalize_structure_type(base["StructureTypeRaw"])

    base["HeightM"], base["HeightSource"] = combine_first_with_source(
        base,
        [
            ("Height_OSM", "osm"),
            ("Height_OVT", "overture"),
            ("Height_MS", "microsoft"),
        ],
    )
    base["HeightM"] = to_numeric_safe(base["HeightM"], index=base.index)

    height_est_stories = (base["HeightM"] / 3.05).round().clip(lower=1, upper=200)
    base["Stories_EstFromHeight"] = height_est_stories.where(base["HeightM"].notna())
    base["NumStories"], base["NumStoriesSource"] = combine_first_with_source(
        base,
        [
            ("Stories_OSM", "osm"),
            ("Stories_OVT", "overture"),
            ("NSI_NumStory", "nsi"),
            ("Stories_EstFromHeight", "height_estimate"),
        ],
    )
    base["NumStories"] = to_numeric_safe(base["NumStories"], index=base.index)

    base["NumUnits"], base["NumUnitsSource"] = combine_first_with_source(
        base,
        [
            ("Units_OSM", "osm"),
            ("NSI_ResUnits", "nsi"),
        ],
    )
    base["NumUnits"] = to_numeric_safe(base["NumUnits"], index=base.index)
    infer_single = (
        base["NumUnits"].isna()
        & base["StructureType"].isin(["residential", "mobile_home"])
        & base["StructureTypeRaw"].fillna("").astype(str).str.lower().str.contains(
            r"house|detached|semidetached|terrace|res1|res2|mobile", regex=True
        )
    )
    base.loc[infer_single, "NumUnits"] = 1
    base.loc[infer_single, "NumUnitsSource"] = "inferred_single_family"

    nsi_people = pd.concat(
        [
            to_numeric_safe(base.get("NSI_Pop2AM"), index=base.index),
            to_numeric_safe(base.get("NSI_Pop2PM"), index=base.index),
            (
                to_numeric_safe(base.get("NSI_EmpNum"), index=base.index).fillna(0)
                + to_numeric_safe(base.get("NSI_Students"), index=base.index).fillna(0)
            ).replace(0, np.nan),
        ],
        axis=1,
    ).max(axis=1, skipna=True)
    base["OccupantCount"] = nsi_people
    base["OccupantCountMethod"] = np.where(
        nsi_people.notna(), "nsi_max_2am_2pm_emp_students", pd.NA
    )

    if census_household_size:
        census_est = base["NumUnits"] * census_household_size
        census_mask = (
            base["OccupantCount"].isna()
            & base["StructureType"].isin(
                ["residential", "condo", "apartment", "mobile_home"]
            )
            & census_est.notna()
        )
        base.loc[census_mask, "OccupantCount"] = census_est.loc[census_mask]
        base.loc[census_mask, "OccupantCountMethod"] = (
            "num_units_x_census_household_size"
        )
    base["CensusAvgHouseholdSize"] = census_household_size
    base["CensusSource"] = census_source

    for column in OUTPUT_COLUMNS:
        if column not in base.columns:
            base[column] = pd.NA
    return base[OUTPUT_COLUMNS].to_crs(epsg=4326).reset_index(drop=True)


def build_city_structures(
    city: str,
    state: str,
    config: PipelineConfig | None = None,
    parcel_source: dict | str | None = None,
) -> gpd.GeoDataFrame:
    config = config or PipelineConfig()
    config.ensure_dirs()

    state_name = normalize_state_name(state)
    city_slug = slugify(city, state_name, config.country)
    print(f"\n=== {city}, {state_name} ===")

    boundary = get_city_boundary(city, state_name, config.country)
    census_household_size, census_source = get_census_household_size(
        city, state_name, config
    )

    overture = load_overture_buildings(city_slug, boundary, config)
    print(f"Overture polygons: {len(overture):,}")
    microsoft = load_microsoft_buildings(city_slug, boundary, config)
    print(f"Microsoft polygons: {len(microsoft):,}")
    base = merge_footprints(overture, microsoft, config)
    footprints_after_overture_microsoft = len(base)
    print(f"Merged footprint polygons (Overture + Microsoft): {footprints_after_overture_microsoft:,}")

    osm = get_osm_buildings(boundary, config)
    print(f"OSM building polygons: {len(osm):,}")
    base = merge_osm_footprints(base, osm, config)
    footprints_after_osm_merge = len(base)
    print(f"Merged footprint polygons (after OSM): {footprints_after_osm_merge:,}")
    base = attach_osm_attributes(base, osm)

    nsi = get_nsi_structures(boundary, config)
    print(f"NSI structure points: {len(nsi):,}")
    base = attach_nsi_attributes(base, nsi)

    parcels = load_city_parcels(
        city_slug,
        city,
        state_name,
        boundary,
        config,
        parcel_source=parcel_source,
    )
    print(f"Parcel polygons: {len(parcels):,}")
    base = attach_parcel_attributes(base, parcels)

    final = finalize_attributes(
        base,
        city=city,
        state=state_name,
        country=config.country,
        census_household_size=census_household_size,
        census_source=census_source,
    )
    validate_output_gdf(final, city_slug, config)
    output_path = config.output_dir / f"{city_slug}_structures.parquet"
    final.to_parquet(output_path, index=False)
    write_metadata_sidecar(
        output_path,
        config,
        {
            "dataset": "city_structures",
            "city_slug": city_slug,
            "city": city,
            "state": state_name,
            "country": config.country,
            "bounds": bounds_tuple(boundary),
            "row_count": len(final),
            "source_counts": {
                "overture_polygons": len(overture),
                "microsoft_polygons": len(microsoft),
                "merged_footprints_overture_microsoft": footprints_after_overture_microsoft,
                "merged_footprints_after_osm": footprints_after_osm_merge,
                "osm_building_polygons": len(osm),
                "nsi_structure_points": len(nsi),
                "parcel_polygons": len(parcels),
            },
            "config": config_metadata(config),
        },
    )
    print(f"Saved {len(final):,} rows to {output_path}")
    return final


def build_many_cities(
    cities: list[dict[str, str]], config: PipelineConfig | None = None
) -> gpd.GeoDataFrame:
    config = config or PipelineConfig()
    config.ensure_dirs()
    outputs = []
    for place in cities:
        outputs.append(
            build_city_structures(
                place["city"],
                place["state"],
                config,
                parcel_source=place.get("parcel_source") or place.get("parcels"),
            )
        )
    if not outputs:
        return empty_gdf()
    combined = gpd.GeoDataFrame(
        pd.concat(outputs, ignore_index=True), geometry="geometry", crs=outputs[0].crs
    )
    validate_output_gdf(combined, "combined_structures", config)
    combined_path = config.output_dir / "structures_master.parquet"
    combined.to_parquet(combined_path, index=False)
    write_metadata_sidecar(
        combined_path,
        config,
        {
            "dataset": "combined_structures",
            "row_count": len(combined),
            "city_count": len(outputs),
            "places": [
                {
                    "city": place["city"],
                    "state": normalize_state_name(place["state"]),
                    "country": config.country,
                }
                for place in cities
            ],
            "config": config_metadata(config),
        },
    )
    print(f"Saved combined output to {combined_path}")
    return combined


def parse_place(value: str) -> dict[str, str]:
    if "," not in value:
        raise argparse.ArgumentTypeError(
            "Use 'City, State', for example 'Bengaluru, Karnataka'"
        )
    city, state = value.rsplit(",", 1)
    return {"city": city.strip(), "state": state.strip()}


def parse_parcel_source_arg(value: str) -> tuple[str, dict]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "Use city_slug=path_or_url, for example bengaluru_karnataka_india=data/parcels.gpkg"
        )
    city_slug, source_value = value.split("=", 1)
    source_value = source_value.strip()
    source = (
        {"url": source_value}
        if source_value.lower().startswith("http")
        else {"path": source_value}
    )
    return city_slug.strip(), source


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build enriched India structure polygons."
    )
    parser.add_argument(
        "--place",
        action="append",
        type=parse_place,
        required=True,
        help="City and state as 'City, State'. Can be passed multiple times.",
    )
    parser.add_argument("--country", default="India")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--no-overture", action="store_true")
    parser.add_argument("--no-microsoft", action="store_true")
    parser.add_argument("--no-osm", action="store_true")
    parser.add_argument("--use-nsi", action="store_true")
    parser.add_argument("--use-census", action="store_true")
    parser.add_argument("--no-parcels", action="store_true")
    parser.add_argument("--strict-sources", action="store_true")
    parser.add_argument("--fail-on-empty-output", action="store_true")
    parser.add_argument("--no-metadata", action="store_true")
    parser.add_argument(
        "--parcel-source",
        action="append",
        type=parse_parcel_source_arg,
        default=[],
        help="Parcel source as city_slug=path_or_url. Can be passed multiple times.",
    )
    args = parser.parse_args()

    config = PipelineConfig(
        country=args.country,
        download_missing=not args.no_download,
        use_overture=not args.no_overture,
        use_microsoft=not args.no_microsoft,
        use_osm=not args.no_osm,
        use_nsi=args.use_nsi,
        use_census=args.use_census,
        use_parcels=not args.no_parcels,
        parcel_sources=dict(args.parcel_source),
        strict_sources=args.strict_sources,
        fail_on_empty_output=args.fail_on_empty_output,
        write_run_metadata=not args.no_metadata,
    )
    build_many_cities(args.place, config)


if __name__ == "__main__":
    main()
