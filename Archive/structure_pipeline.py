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
from dataclasses import dataclass, field
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
import polars as pl
import pyarrow.compute as pc
import pyarrow.dataset as ds
import requests
from shapely import to_wkt
from shapely.geometry import box, shape


MICROSOFT_DATASET_LINKS = (
    "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
)
NSI_STRUCTURES_URL = "https://nsi.sec.usace.army.mil/nsiapi/structures?fmt=fc"
CENSUS_ACS_URL = "https://api.census.gov/data/{year}/acs/acs5"


STATE_FIPS = {
    "alabama": "01",
    "alaska": "02",
    "arizona": "04",
    "arkansas": "05",
    "california": "06",
    "colorado": "08",
    "connecticut": "09",
    "delaware": "10",
    "district of columbia": "11",
    "florida": "12",
    "georgia": "13",
    "hawaii": "15",
    "idaho": "16",
    "illinois": "17",
    "indiana": "18",
    "iowa": "19",
    "kansas": "20",
    "kentucky": "21",
    "louisiana": "22",
    "maine": "23",
    "maryland": "24",
    "massachusetts": "25",
    "michigan": "26",
    "minnesota": "27",
    "mississippi": "28",
    "missouri": "29",
    "montana": "30",
    "nebraska": "31",
    "nevada": "32",
    "new hampshire": "33",
    "new jersey": "34",
    "new mexico": "35",
    "new york": "36",
    "north carolina": "37",
    "north dakota": "38",
    "ohio": "39",
    "oklahoma": "40",
    "oregon": "41",
    "pennsylvania": "42",
    "rhode island": "44",
    "south carolina": "45",
    "south dakota": "46",
    "tennessee": "47",
    "texas": "48",
    "utah": "49",
    "vermont": "50",
    "virginia": "51",
    "washington": "53",
    "west virginia": "54",
    "wisconsin": "55",
    "wyoming": "56",
}

STATE_ABBR_TO_NAME = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
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
    "FootprintArea_m2",
    "Confidence_MS",
    "HasParts",
    "CensusAvgHouseholdSize",
    "CensusSource",
    "geometry",
]

POLARS_STRING_COLUMNS = {
    "StructureID",
    "City",
    "State",
    "Country",
    "FootprintSource",
    "OvertureID",
    "MicrosoftID",
    "OSMID",
    "NSI_FD_ID",
    "StructureType",
    "StructureTypeRaw",
    "StructureTypeSource",
    "BuildingName",
    "BuildingNameSource",
    "NumUnitsSource",
    "NumStoriesSource",
    "HeightSource",
    "OccupantCountMethod",
    "CBFIPS",
    "CensusSource",
}

POLARS_NUMERIC_COLUMNS = {
    "NSI_RecordCount",
    "NumUnits",
    "NumStories",
    "HeightM",
    "OccupantCount",
    "NSI_Pop2AM",
    "NSI_Pop2PM",
    "NSI_EmpNum",
    "NSI_Students",
    "FootprintArea_m2",
    "Confidence_MS",
    "CensusAvgHouseholdSize",
}

POLARS_BOOLEAN_COLUMNS = {"HasParts"}


@dataclass
class PipelineConfig:
    data_dir: Path = Path("data")
    output_dir: Path = Path("data/output")
    raw_dir: Path = Path("data/raw")
    cache_dir: Path = Path("cache")
    country: str = "USA"
    download_missing: bool = True
    use_overture: bool = True
    use_microsoft: bool = True
    use_osm: bool = True
    use_nsi: bool = True
    use_census: bool = True
    add_microsoft_unmatched: bool = True
    overture_release: str | None = None
    nsi_tile_size_deg: float = 0.08
    request_timeout_sec: int = 90
    microsoft_zoom: int = 9
    use_polars: bool = True
    sql_server_url: str | None = None
    sql_server_table: str = "structures_master"
    sql_server_schema: str | None = None
    sql_server_if_exists: str = "replace"
    sql_server_chunksize: int = 50000
    sql_server_fast_executemany: bool = True
    sql_server_geometry_column: str = "geometry_wkt"
    sql_server_export_city_tables: bool = False
    generic_microsoft_cache_slugs: set[str] = field(
        default_factory=lambda: {"houston_texas_usa"}
    )

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.output_dir = Path(self.output_dir)
        self.raw_dir = Path(self.raw_dir)
        self.cache_dir = Path(self.cache_dir)
        self.generic_microsoft_cache_slugs = set(self.generic_microsoft_cache_slugs)
        self.validate()

    def validate(self) -> None:
        if self.sql_server_if_exists not in {"fail", "replace", "append"}:
            raise ValueError("sql_server_if_exists must be fail, replace, or append")
        if self.sql_server_chunksize <= 0:
            raise ValueError("sql_server_chunksize must be positive")

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.output_dir, self.raw_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)


def slugify(*parts: str) -> str:
    text = "_".join(str(part) for part in parts if part)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "place"


def normalize_state_name(state: str) -> str:
    stripped = state.strip()
    if len(stripped) == 2 and stripped.upper() in STATE_ABBR_TO_NAME:
        return STATE_ABBR_TO_NAME[stripped.upper()]
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
    return gpd.GeoDataFrame({column: [] for column in columns}, geometry=[], crs=crs)


def empty_output_gdf(crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    data = {column: [] for column in OUTPUT_COLUMNS if column != "geometry"}
    return gpd.GeoDataFrame(data, geometry=[], crs=crs)


def apply_polars_output_schema(
    gdf: gpd.GeoDataFrame, use_polars: bool = True
) -> gpd.GeoDataFrame:
    if gdf.empty:
        return empty_output_gdf(crs=gdf.crs or "EPSG:4326")

    for column in OUTPUT_COLUMNS:
        if column != "geometry" and column not in gdf.columns:
            gdf[column] = pd.NA

    geometry_name = gdf.geometry.name
    geometry = gdf.geometry.reset_index(drop=True)
    crs = gdf.crs
    attribute_columns = [column for column in OUTPUT_COLUMNS if column != "geometry"]
    attributes = pd.DataFrame(gdf[attribute_columns]).reset_index(drop=True)
    if not use_polars:
        return gpd.GeoDataFrame(attributes, geometry=geometry, crs=crs).to_crs(
            epsg=4326
        )

    frame = pl.from_pandas(attributes)
    cast_exprs = []
    for column in POLARS_STRING_COLUMNS:
        if column in frame.columns:
            cast_exprs.append(pl.col(column).cast(pl.Utf8, strict=False))
    for column in POLARS_NUMERIC_COLUMNS:
        if column in frame.columns:
            cast_exprs.append(pl.col(column).cast(pl.Float64, strict=False))
    for column in POLARS_BOOLEAN_COLUMNS:
        if column in frame.columns:
            cast_exprs.append(pl.col(column).cast(pl.Boolean, strict=False))
    if cast_exprs:
        frame = frame.with_columns(cast_exprs)

    attributes = frame.select(attribute_columns).to_pandas()
    return gpd.GeoDataFrame(
        attributes, geometry=geometry.rename(geometry_name), crs=crs
    ).to_crs(epsg=4326)


def structure_geodataframe_to_polars(
    gdf: gpd.GeoDataFrame, geometry_column: str = "geometry_wkt"
) -> pl.DataFrame:
    if gdf.empty:
        columns = [column for column in OUTPUT_COLUMNS if column != "geometry"]
        return pl.DataFrame(
            {**{column: [] for column in columns}, geometry_column: []}
        )

    geometry_name = gdf.geometry.name
    attributes = pd.DataFrame(gdf.drop(columns=[geometry_name])).reset_index(
        drop=True
    )
    frame = pl.from_pandas(attributes)
    geometry_values = to_wkt(gdf.geometry.array)
    return frame.with_columns(pl.Series(geometry_column, geometry_values))


def split_sql_table_name(table_name: str, schema: str | None) -> tuple[str | None, str]:
    if "." in table_name and schema is None:
        schema_name, table = table_name.split(".", 1)
        return schema_name or None, table
    return schema, table_name


def validate_sql_identifier(value: str, label: str) -> None:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
        raise ValueError(
            f"{label} must contain only letters, numbers, and underscores, "
            "and must not start with a number."
        )


def export_to_sql_server(
    gdf: gpd.GeoDataFrame, config: PipelineConfig, table_name: str | None = None
) -> None:
    if not config.sql_server_url:
        return
    from sqlalchemy import create_engine

    table = table_name or config.sql_server_table
    schema, table = split_sql_table_name(table, config.sql_server_schema)
    validate_sql_identifier(table, "sql_server_table")
    if schema:
        validate_sql_identifier(schema, "sql_server_schema")

    frame = structure_geodataframe_to_polars(
        gdf, geometry_column=config.sql_server_geometry_column
    )
    pandas_frame = frame.to_pandas()
    engine = create_engine(
        config.sql_server_url,
        fast_executemany=config.sql_server_fast_executemany,
    )
    with engine.begin() as connection:
        pandas_frame.to_sql(
            table,
            connection,
            schema=schema,
            if_exists=config.sql_server_if_exists,
            index=False,
            chunksize=config.sql_server_chunksize,
        )
    qualified_table = f"{schema}.{table}" if schema else table
    print(f"Exported {len(pandas_frame):,} rows to SQL Server table {qualified_table}")


def concat_structure_outputs(
    outputs: list[gpd.GeoDataFrame], use_polars: bool = True
) -> gpd.GeoDataFrame:
    if not outputs:
        return empty_output_gdf()
    if not use_polars:
        return gpd.GeoDataFrame(
            pd.concat(outputs, ignore_index=True),
            geometry="geometry",
            crs=outputs[0].crs,
        )

    geometry_name = outputs[0].geometry.name
    attribute_columns = [column for column in OUTPUT_COLUMNS if column != "geometry"]
    frames = []
    geometries = []
    for output in outputs:
        output = apply_polars_output_schema(output, use_polars=True)
        frames.append(pl.from_pandas(pd.DataFrame(output[attribute_columns])))
        geometries.append(pd.Series(output.geometry.reset_index(drop=True)))
    attributes = pl.concat(frames, how="vertical_relaxed").to_pandas()
    geometry = gpd.GeoSeries(
        pd.concat(geometries, ignore_index=True), crs=outputs[0].crs
    )
    return gpd.GeoDataFrame(
        attributes, geometry=geometry.rename(geometry_name), crs=outputs[0].crs
    )


def clean_geom(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    polygon_types = {"Polygon", "MultiPolygon"}
    cleaned = gdf[
        gdf.geometry.notna()
        & gdf.geometry.is_valid
        & gdf.geometry.geom_type.isin(polygon_types)
    ].copy()
    return cleaned


def clip_to_boundary(
    gdf: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    gdf = gdf.to_crs(boundary.crs)
    clipped = gpd.clip(gdf, boundary)
    return clean_geom(clipped).reset_index(drop=True)


def get_city_boundary(
    city: str, state: str, country: str = "USA"
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

    download_overture_buildings(bounds, city_path, config)
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
    subprocess.run(cmd, check=True)
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

    out = gpd.GeoDataFrame(
        {
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
        projected_crs = "EPSG:5070"
    base["FootprintArea_m2"] = base.to_crs(projected_crs).geometry.area.values
    return base


def finalize_attributes(
    base: gpd.GeoDataFrame,
    city: str,
    state: str,
    country: str,
    census_household_size: float | None,
    census_source: str | None,
    use_polars: bool = True,
) -> gpd.GeoDataFrame:
    if base.empty:
        return empty_output_gdf()

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
            & base["StructureType"].isin(["residential", "condo", "apartment", "mobile_home"])
            & census_est.notna()
        )
        base.loc[census_mask, "OccupantCount"] = census_est.loc[census_mask]
        base.loc[census_mask, "OccupantCountMethod"] = "num_units_x_census_household_size"
    base["CensusAvgHouseholdSize"] = census_household_size
    base["CensusSource"] = census_source

    for column in OUTPUT_COLUMNS:
        if column not in base.columns:
            base[column] = pd.NA
    return apply_polars_output_schema(
        base[OUTPUT_COLUMNS], use_polars=use_polars
    ).reset_index(drop=True)


def build_city_structures(
    city: str,
    state: str,
    config: PipelineConfig | None = None,
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
    print(f"Merged footprint polygons: {len(base):,}")

    osm = get_osm_buildings(boundary, config)
    print(f"OSM building polygons: {len(osm):,}")
    base = attach_osm_attributes(base, osm)

    nsi = get_nsi_structures(boundary, config)
    print(f"NSI structure points: {len(nsi):,}")
    base = attach_nsi_attributes(base, nsi)

    final = finalize_attributes(
        base,
        city=city,
        state=state_name,
        country=config.country,
        census_household_size=census_household_size,
        census_source=census_source,
        use_polars=config.use_polars,
    )
    output_path = config.output_dir / f"{city_slug}_structures.parquet"
    final.to_parquet(output_path, index=False)
    if config.sql_server_export_city_tables:
        export_to_sql_server(final, config, table_name=f"{city_slug}_structures")
    print(f"Saved {len(final):,} rows to {output_path}")
    return final


def build_many_cities(
    cities: list[dict[str, str]], config: PipelineConfig | None = None
) -> gpd.GeoDataFrame:
    config = config or PipelineConfig()
    config.ensure_dirs()
    outputs = []
    for place in cities:
        outputs.append(build_city_structures(place["city"], place["state"], config))
    if not outputs:
        return empty_output_gdf()
    combined = concat_structure_outputs(outputs, use_polars=config.use_polars)
    combined_path = config.output_dir / "structures_master.parquet"
    combined.to_parquet(combined_path, index=False)
    export_to_sql_server(combined, config)
    print(f"Saved combined output to {combined_path}")
    return combined


def parse_place(value: str) -> dict[str, str]:
    if "," not in value:
        raise argparse.ArgumentTypeError("Use 'City, State', for example 'Houston, Texas'")
    city, state = value.rsplit(",", 1)
    return {"city": city.strip(), "state": state.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build enriched US structure polygons.")
    parser.add_argument(
        "--place",
        action="append",
        type=parse_place,
        required=True,
        help="City and state as 'City, State'. Can be passed multiple times.",
    )
    parser.add_argument("--country", default="USA")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--no-overture", action="store_true")
    parser.add_argument("--no-microsoft", action="store_true")
    parser.add_argument("--no-osm", action="store_true")
    parser.add_argument("--no-nsi", action="store_true")
    parser.add_argument("--no-census", action="store_true")
    parser.add_argument(
        "--no-polars",
        action="store_true",
        help="Disable Polars schema/cast and concatenation fast paths.",
    )
    parser.add_argument(
        "--sql-server-url",
        default=os.getenv("STRUCTURES_SQL_SERVER_URL"),
        help=(
            "Optional SQLAlchemy SQL Server URL. Can also be set with "
            "STRUCTURES_SQL_SERVER_URL."
        ),
    )
    parser.add_argument(
        "--sql-server-table",
        default="structures_master",
        help="SQL Server table for the combined output. Use --sql-server-schema for schema.",
    )
    parser.add_argument(
        "--sql-server-schema",
        default=None,
        help="Optional SQL Server schema, for example dbo.",
    )
    parser.add_argument(
        "--sql-server-if-exists",
        choices=["fail", "replace", "append"],
        default="replace",
        help="Behavior if the SQL Server table already exists.",
    )
    parser.add_argument(
        "--sql-server-chunksize",
        type=int,
        default=50000,
        help="Rows per batch for pandas.to_sql SQL Server writes.",
    )
    parser.add_argument(
        "--sql-server-no-fast-executemany",
        action="store_true",
        help="Disable pyodbc fast_executemany for SQL Server exports.",
    )
    parser.add_argument(
        "--sql-server-geometry-column",
        default="geometry_wkt",
        help="Output SQL column name for geometry serialized as WKT.",
    )
    parser.add_argument(
        "--sql-server-city-tables",
        action="store_true",
        help="Also export each city output to its own SQL Server table.",
    )
    args = parser.parse_args()

    config = PipelineConfig(
        country=args.country,
        download_missing=not args.no_download,
        use_overture=not args.no_overture,
        use_microsoft=not args.no_microsoft,
        use_osm=not args.no_osm,
        use_nsi=not args.no_nsi,
        use_census=not args.no_census,
        use_polars=not args.no_polars,
        sql_server_url=args.sql_server_url,
        sql_server_table=args.sql_server_table,
        sql_server_schema=args.sql_server_schema,
        sql_server_if_exists=args.sql_server_if_exists,
        sql_server_chunksize=args.sql_server_chunksize,
        sql_server_fast_executemany=not args.sql_server_no_fast_executemany,
        sql_server_geometry_column=args.sql_server_geometry_column,
        sql_server_export_city_tables=args.sql_server_city_tables,
    )
    build_many_cities(args.place, config)


if __name__ == "__main__":
    main()
