from __future__ import annotations

import gzip
import json
import os
import logging
import math
import re
import ssl
from pathlib import Path
from urllib.request import urlopen

import certifi
import geopandas as gpd
import mercantile
import numpy as np
import pandas as pd
import requests
from shapely import wkb, wkt
from shapely.geometry import box, shape

from structures_pipeline.config import PipelineConfig
from structures_pipeline.constants import (
    CENSUS_ACS_URL,
    MICROSOFT_DATASET_LINKS_URL,
    NSI_STRUCTURES_URL,
    OVERTURE_AZURE_BUILDINGS_GLOB,
    OVERTURE_STAC_URL,
    PARCEL_FIELD_ALIASES,
    PARCEL_TEXT_COLUMNS,
)
from structures_pipeline.geometry import (
    assign_footprints_to_place,
    bounds_tuple,
    clean_geom,
    dedupe_fallback_footprints,
    empty_gdf,
    estimated_projected_crs,
    normalize_boundary,
)
from structures_pipeline.utils import parse_height_meters, slugify, to_numeric_safe

LOGGER = logging.getLogger(__name__)


def read_wkb_parquet(path: Path, crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    try:
        gdf = gpd.read_parquet(path)
        if isinstance(gdf, gpd.GeoDataFrame) and gdf.geometry.name in gdf.columns:
            return gdf if gdf.crs else gdf.set_crs(crs)
    except Exception:
        pass

    df = pd.read_parquet(path)
    if "geometry" not in df.columns:
        return empty_gdf(df.columns, crs=crs)
    geometry = gpd.GeoSeries.from_wkb(df.pop("geometry"), crs=crs)
    return gpd.GeoDataFrame(df, geometry=geometry, crs=crs)


def resolve_overture_release(config: PipelineConfig) -> str | None:
    if config.source_version and config.source_version != "latest":
        return config.source_version
    if not config.download_missing:
        return "latest"
    try:
        response = requests.get(OVERTURE_STAC_URL, timeout=config.request_timeout_sec)
        response.raise_for_status()
        latest = response.json().get("latest")
        if latest:
            return str(latest)
    except Exception as exc:
        LOGGER.warning("Could not resolve latest Overture release: %s", exc)
    return None


def _sql_quote(value: str | Path) -> str:
    return str(value).replace("'", "''")


def _decode_sql_geometry(value):
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytearray):
        value = bytes(value)
    if isinstance(value, bytes):
        return wkb.loads(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return wkb.loads(bytes.fromhex(stripped))
        except Exception:
            return wkt.loads(stripped)
    if hasattr(value, "wkb"):
        return value
    return value


def read_sql_geometry_source(source: dict, config: PipelineConfig) -> gpd.GeoDataFrame:
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise RuntimeError("sqlalchemy is required for SQL geometry sources") from exc

    connection = source.get("connection")
    connection_env = source.get("connection_env") or "STRUCTURES_SQL_URL"
    if not connection:
        connection = os.environ.get(connection_env)
    if not connection:
        raise RuntimeError(f"Missing SQL connection string. Set {connection_env} or pass connection in config.")

    table = source.get("table")
    query = source.get("query")
    if table and query:
        raise ValueError("SQL source can use table or query, not both")
    if query:
        sql = str(query)
    elif table:
        sql = f"SELECT * FROM {table}"
        where = source.get("where")
        if where:
            sql = f"{sql} WHERE {where}"
    else:
        raise ValueError("SQL source requires table or query")

    engine = create_engine(connection)
    with engine.connect() as conn:
        df = pd.read_sql_query(text(sql), conn)
    geom_column = source.get("geom_column", "geom")
    if geom_column not in df.columns:
        raise ValueError(f"SQL source is missing geometry column: {geom_column}")
    geometry = df.pop(geom_column).map(_decode_sql_geometry)
    crs = source.get("crs", "EPSG:4326")
    return gpd.GeoDataFrame(df, geometry=geometry, crs=crs)


def _sqlserver_name(name: str) -> str:
    parts = [part.strip() for part in name.split(".") if part.strip()]
    if not parts:
        raise ValueError("SQL Server identifier cannot be empty")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_@$#]*", part) for part in parts):
        raise ValueError(f"Unsafe SQL Server identifier: {name}")
    return ".".join(f"[{part}]" for part in parts)


def read_sql_baseline_source(source: dict, config: PipelineConfig) -> gpd.GeoDataFrame:
    table = source.get("table")
    query = source.get("query")
    geom_column = source.get("geom_column", "geom")
    use_sqlserver_methods = bool(source.get("sqlserver_geometry_methods"))
    if table and not query and use_sqlserver_methods:
        id_column = source.get("id_column")
        id_select = f", {_sqlserver_name(id_column)} AS BaselineID" if id_column else ""
        where = f" WHERE {source.get('where')}" if source.get("where") else ""
        baseline_source = dict(source)
        baseline_source["query"] = (
            f"SELECT {_sqlserver_name(geom_column)}.STAsBinary() AS geometry_wkb, "
            f"{_sqlserver_name(geom_column)}.STSrid AS geometry_srid{id_select} "
            f"FROM {_sqlserver_name(table)}{where}"
        )
        baseline_source.pop("table", None)
        baseline_source["geom_column"] = "geometry_wkb"
        raw = read_sql_geometry_source(baseline_source, config)
        if "geometry_srid" in raw.columns:
            srid = pd.to_numeric(raw.pop("geometry_srid"), errors="coerce").dropna()
            if not srid.empty and srid.iloc[0]:
                raw = raw.set_crs(f"EPSG:{int(srid.iloc[0])}", allow_override=True)
    else:
        raw = read_sql_geometry_source(source, config)

    if raw.empty:
        return empty_gdf(["BaselineID"])
    baseline = raw.to_crs(epsg=4326).reset_index(drop=True)
    id_column = source.get("id_column")
    if "BaselineID" not in baseline.columns:
        if id_column and id_column in baseline.columns:
            baseline["BaselineID"] = baseline[id_column].astype(str)
        else:
            baseline["BaselineID"] = [f"baseline_{i}" for i in range(len(baseline))]
    return baseline[["BaselineID", "geometry"]]


def buffered_baseline_boundary(baseline: gpd.GeoDataFrame, buffer_meters: float) -> gpd.GeoDataFrame:
    if baseline.empty:
        raise ValueError("SQL baseline returned no geometries")
    work_crs = estimated_projected_crs(baseline)
    buffered = baseline.to_crs(work_crs).geometry.buffer(buffer_meters)
    unioned = buffered.union_all() if hasattr(buffered, "union_all") else buffered.unary_union
    boundary = gpd.GeoDataFrame(geometry=[unioned], crs=work_crs).to_crs(epsg=4326)
    return normalize_boundary(boundary)


def attach_baseline_proximity(
    structures: gpd.GeoDataFrame,
    baseline: gpd.GeoDataFrame,
    buffer_meters: float,
) -> gpd.GeoDataFrame:
    if structures.empty or baseline.empty:
        return structures
    work_crs = estimated_projected_crs(structures, baseline)
    points = structures[["StructureID", "geometry"]].copy().to_crs(work_crs)
    points["geometry"] = points.geometry.representative_point()
    baseline_work = baseline[["BaselineID", "geometry"]].copy().to_crs(work_crs)
    nearest = gpd.sjoin_nearest(
        points,
        baseline_work,
        how="left",
        distance_col="BaselineDistance_m",
    ).drop_duplicates("StructureID")
    nearest = nearest.set_index("StructureID")

    out = structures.set_index("StructureID")
    out["BaselineID"] = nearest["BaselineID"].reindex(out.index)
    out["BaselineDistance_m"] = nearest["BaselineDistance_m"].reindex(out.index)
    out["BaselineBuffer_m"] = buffer_meters
    return out.reset_index()


def standardize_sql_footprints(gdf: gpd.GeoDataFrame, place: pd.Series, source: dict) -> gpd.GeoDataFrame:
    if gdf.empty:
        return empty_gdf()
    gdf = clean_geom(gdf.to_crs(epsg=4326)).reset_index(drop=True)
    city_slug = slugify(place["City"], place["State"], "USA")
    id_column = source.get("id_column")
    if id_column and id_column in gdf.columns:
        source_ids = gdf[id_column].astype(str)
    else:
        source_ids = pd.Series(gdf.index, index=gdf.index).astype(str)
    source_name = source.get("source_name") or "sql"
    structure_type_column = source.get("structure_type_column")
    height_column = source.get("height_column")
    stories_column = source.get("stories_column")
    out = gpd.GeoDataFrame(
        {
            "StructureID": f"sql_{place['PlaceGEOID']}_{city_slug}_" + source_ids,
            "FootprintSource": source_name,
            "OvertureID": pd.Series(pd.NA, index=gdf.index, dtype="string"),
            "MicrosoftID": pd.Series(pd.NA, index=gdf.index, dtype="string"),
            "BuildingName_OVT": pd.Series(pd.NA, index=gdf.index),
            "Height_OVT": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "Stories_OVT": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "OvertureSubtype": pd.Series(pd.NA, index=gdf.index),
            "OvertureClass": pd.Series(pd.NA, index=gdf.index),
            "SQLStructureType": gdf[structure_type_column] if structure_type_column in gdf.columns else pd.Series(pd.NA, index=gdf.index),
            "SQLHeight": to_numeric_safe(gdf[height_column], index=gdf.index) if height_column in gdf.columns else pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "SQLStories": to_numeric_safe(gdf[stories_column], index=gdf.index) if stories_column in gdf.columns else pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "HasParts": pd.Series(pd.NA, index=gdf.index),
            "Height_MS": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "Confidence_MS": pd.Series(np.nan, index=gdf.index, dtype="float64"),
        },
        geometry=gdf.geometry,
        crs="EPSG:4326",
    )
    return out.reset_index(drop=True)


def load_sql_footprints(
    place: pd.Series,
    boundary: gpd.GeoDataFrame,
    config: PipelineConfig,
) -> gpd.GeoDataFrame:
    source = config.sql_footprint_source
    if not config.use_sql or not source:
        return empty_gdf()
    try:
        raw = read_sql_geometry_source(source, config)
    except Exception as exc:
        LOGGER.warning("SQL footprint source skipped for %s: %s", place["PlaceGEOID"], exc)
        return empty_gdf()
    standardized = standardize_sql_footprints(raw, place, source)
    return assign_footprints_to_place(standardized, boundary).reset_index(drop=True)


def download_overture_with_duckdb(
    boundary: gpd.GeoDataFrame,
    output_path: Path,
    release: str,
) -> None:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("duckdb is required for remote Overture querying") from exc

    minx, miny, maxx, maxy = bounds_tuple(boundary)
    glob = OVERTURE_AZURE_BUILDINGS_GLOB.format(release=release)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
        sql = f"""
            COPY (
                SELECT
                    id AS OvertureID,
                    names.primary AS BuildingName_OVT,
                    TRY_CAST(height AS DOUBLE) AS Height_OVT,
                    TRY_CAST(num_floors AS DOUBLE) AS Stories_OVT,
                    subtype AS OvertureSubtype,
                    class AS OvertureClass,
                    has_parts AS HasParts,
                    geometry
                FROM read_parquet('{_sql_quote(glob)}', hive_partitioning = 1)
                WHERE bbox.xmin <= {maxx}
                  AND bbox.xmax >= {minx}
                  AND bbox.ymin <= {maxy}
                  AND bbox.ymax >= {miny}
            )
            TO '{_sql_quote(output_path)}' (FORMAT PARQUET)
        """
        con.execute(sql)
    finally:
        con.close()


def load_overture_buildings(
    place: pd.Series,
    boundary: gpd.GeoDataFrame,
    config: PipelineConfig,
    release: str | None,
) -> gpd.GeoDataFrame:
    if not config.use_overture:
        return empty_gdf()
    city_slug = slugify(place["City"], place["State"], "USA")
    raw_path = config.raw_dir / f"overture_{place['PlaceGEOID']}_{city_slug}.parquet"
    if (not raw_path.exists() or config.overwrite_raw) and config.download_missing:
        if not release or release == "latest":
            LOGGER.warning("Overture skipped: latest release could not be resolved")
        else:
            try:
                LOGGER.info("Querying Overture %s for %s", release, city_slug)
                download_overture_with_duckdb(boundary, raw_path, release)
            except Exception as exc:
                LOGGER.warning("Overture source skipped for %s: %s", city_slug, exc)
    if not raw_path.exists():
        LOGGER.info("Overture source skipped for %s: no cached file", city_slug)
        return empty_gdf()

    raw = read_wkb_parquet(raw_path)
    if raw.empty:
        return empty_gdf()
    raw = clean_geom(raw.to_crs(epsg=4326)).reset_index(drop=True)
    out = gpd.GeoDataFrame(
        {
            "StructureID": "ovt_" + raw.get("OvertureID", pd.Series(raw.index)).astype(str),
            "FootprintSource": "overture",
            "OvertureID": raw.get("OvertureID", pd.Series(pd.NA, index=raw.index)).astype("string"),
            "MicrosoftID": pd.Series(pd.NA, index=raw.index, dtype="string"),
            "BuildingName_OVT": raw.get("BuildingName_OVT", pd.Series(pd.NA, index=raw.index)),
            "Height_OVT": to_numeric_safe(raw.get("Height_OVT"), index=raw.index),
            "Stories_OVT": to_numeric_safe(raw.get("Stories_OVT"), index=raw.index),
            "OvertureSubtype": raw.get("OvertureSubtype", pd.Series(pd.NA, index=raw.index)),
            "OvertureClass": raw.get("OvertureClass", pd.Series(pd.NA, index=raw.index)),
            "HasParts": raw.get("HasParts", pd.Series(pd.NA, index=raw.index)),
            "Height_MS": pd.Series(np.nan, index=raw.index, dtype="float64"),
            "Confidence_MS": pd.Series(np.nan, index=raw.index, dtype="float64"),
        },
        geometry=raw.geometry,
        crs="EPSG:4326",
    )
    return assign_footprints_to_place(out, boundary).reset_index(drop=True)


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


def quadkeys_for_bounds(bounds: tuple[float, float, float, float], zoom: int) -> list[str]:
    minx, miny, maxx, maxy = bounds
    return sorted(
        {mercantile.quadkey(tile) for tile in mercantile.tiles(minx, miny, maxx, maxy, zooms=[zoom])}
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
    boundary: gpd.GeoDataFrame,
    output_path: Path,
    config: PipelineConfig,
) -> gpd.GeoDataFrame:
    bounds = bounds_tuple(boundary)
    quad_keys = quadkeys_for_bounds(bounds, zoom=config.microsoft_zoom)
    links = read_remote_csv(MICROSOFT_DATASET_LINKS_URL, dtype=str)
    pieces: list[gpd.GeoDataFrame] = []
    minx, miny, maxx, maxy = bounds

    for quad_key in quad_keys:
        rows = links[links["QuadKey"] == quad_key]
        if rows.empty:
            continue
        for url in rows["Url"].dropna().unique():
            tile = read_microsoft_tile(url)
            if tile.empty:
                continue
            tile = tile.cx[minx:maxx, miny:maxy]
            if not tile.empty:
                pieces.append(tile)

    if not pieces:
        return empty_gdf()
    microsoft = gpd.GeoDataFrame(
        pd.concat(pieces, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )
    microsoft = clean_geom(microsoft)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    microsoft.to_parquet(output_path, index=False)
    return microsoft


def standardize_microsoft(gdf: gpd.GeoDataFrame, place: pd.Series) -> gpd.GeoDataFrame:
    if gdf.empty:
        return empty_gdf()
    gdf = clean_geom(gdf.to_crs(epsg=4326)).reset_index(drop=True)
    city_slug = slugify(place["City"], place["State"], "USA")
    index = pd.Series(gdf.index, index=gdf.index).astype(str)
    out = gpd.GeoDataFrame(
        {
            "StructureID": f"msft_{place['PlaceGEOID']}_{city_slug}_" + index,
            "FootprintSource": "microsoft_fallback",
            "OvertureID": pd.Series(pd.NA, index=gdf.index, dtype="string"),
            "MicrosoftID": f"msft_{place['PlaceGEOID']}_{city_slug}_" + index,
            "BuildingName_OVT": pd.Series(pd.NA, index=gdf.index),
            "Height_OVT": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "Stories_OVT": pd.Series(np.nan, index=gdf.index, dtype="float64"),
            "OvertureSubtype": pd.Series(pd.NA, index=gdf.index),
            "OvertureClass": pd.Series(pd.NA, index=gdf.index),
            "HasParts": pd.Series(False, index=gdf.index),
            "Height_MS": to_numeric_safe(gdf.get("height"), index=gdf.index).replace(-1, np.nan),
            "Confidence_MS": to_numeric_safe(gdf.get("confidence"), index=gdf.index).replace(-1, np.nan),
        },
        geometry=gdf.geometry,
        crs="EPSG:4326",
    )
    return out.reset_index(drop=True)


def load_microsoft_fallback(
    place: pd.Series,
    boundary: gpd.GeoDataFrame,
    config: PipelineConfig,
    primary: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    if not config.use_microsoft or not config.add_microsoft_fallback:
        return empty_gdf()
    city_slug = slugify(place["City"], place["State"], "USA")
    raw_path = config.raw_dir / f"microsoft_{place['PlaceGEOID']}_{city_slug}.parquet"
    if raw_path.exists() and not config.overwrite_raw:
        raw = gpd.read_parquet(raw_path)
    elif config.download_missing:
        try:
            raw = download_microsoft_buildings(boundary, raw_path, config)
        except Exception as exc:
            LOGGER.warning("Microsoft source skipped for %s: %s", city_slug, exc)
            return empty_gdf()
    else:
        LOGGER.info("Microsoft source skipped for %s: no cached file", city_slug)
        return empty_gdf()
    standardized = standardize_microsoft(raw, place)
    assigned = assign_footprints_to_place(standardized, boundary)
    return dedupe_fallback_footprints(
        primary,
        assigned,
        overlap_ratio_threshold=config.microsoft_overlap_ratio_threshold,
    )


def get_osm_buildings(boundary: gpd.GeoDataFrame, config: PipelineConfig) -> gpd.GeoDataFrame:
    if not config.use_osm:
        return empty_gdf()
    try:
        import osmnx as ox

        raw = ox.features_from_polygon(boundary.geometry.iloc[0], tags={"building": True}).reset_index()
    except Exception as exc:
        LOGGER.warning("OSM source skipped: %s", exc)
        return empty_gdf()
    if raw.empty:
        return empty_gdf()
    raw = clean_geom(raw)
    if raw.empty:
        return empty_gdf()
    units = to_numeric_safe(raw.get("building:flats"), index=raw.index)
    for column in ("residential:units", "building:units", "units"):
        if column in raw.columns:
            units = units.combine_first(to_numeric_safe(raw[column], index=raw.index))
    osmid = raw.get("osmid", raw.get("id", pd.Series(raw.index, index=raw.index)))
    return gpd.GeoDataFrame(
        {
            "OSMID": osmid.astype("string"),
            "OSM_StructureType": raw.get("building", pd.Series(pd.NA, index=raw.index)),
            "Stories_OSM": to_numeric_safe(raw.get("building:levels"), index=raw.index),
            "Height_OSM": parse_height_meters(raw.get("height"), index=raw.index),
            "Units_OSM": units,
        },
        geometry=raw.geometry,
        crs=raw.crs,
    ).to_crs(epsg=4326)


def attach_osm_attributes(base: gpd.GeoDataFrame, osm: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    columns = ["OSMID", "OSM_StructureType", "Stories_OSM", "Height_OSM", "Units_OSM"]
    for column in columns:
        if column not in base.columns:
            base[column] = np.nan if column in {"Stories_OSM", "Height_OSM", "Units_OSM"} else pd.NA
    if base.empty or osm.empty:
        return base
    points = base[["StructureID", "geometry"]].copy()
    points["geometry"] = points.geometry.representative_point()
    joined = gpd.sjoin(points, osm[columns + ["geometry"]], how="left", predicate="within")
    joined = joined.drop_duplicates("StructureID").set_index("StructureID")
    base = base.set_index("StructureID")
    for column in columns:
        base[column] = joined[column].reindex(base.index).combine_first(base[column])
    return base.reset_index()


def iter_boundary_tiles(boundary: gpd.GeoDataFrame, step_deg: float):
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
            if tile_geom.intersects(polygon):
                yield gpd.GeoDataFrame(geometry=[tile_geom], crs=boundary.crs)


def get_nsi_structures(boundary: gpd.GeoDataFrame, config: PipelineConfig) -> gpd.GeoDataFrame:
    if not config.use_nsi:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
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
            LOGGER.warning("NSI tile skipped: %s", exc)
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
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    nsi = gpd.GeoDataFrame(pd.concat(pieces, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    nsi = nsi[nsi.geometry.notna()].copy()
    return nsi[nsi.geometry.within(boundary.geometry.iloc[0])].reset_index(drop=True)


def _mode_value(series: pd.Series):
    values = series.dropna()
    mode = values.mode()
    return mode.iloc[0] if not mode.empty else (values.iloc[0] if not values.empty else pd.NA)


def _first_value(series: pd.Series):
    values = series.dropna()
    return values.iloc[0] if not values.empty else pd.NA


def _sum_min_count(series: pd.Series):
    return series.sum(min_count=1)


def attach_nsi_attributes(base: gpd.GeoDataFrame, nsi: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    columns = [
        "NSI_FD_ID",
        "NSI_RecordCount",
        "NSI_OccType",
        "NSI_DamageCategory",
        "NSI_NumStory",
        "NSI_ResUnits",
        "NSI_EmpNum",
        "NSI_Students",
        "NSI_Pop2AM",
        "NSI_Pop2PM",
    ]
    for column in columns:
        if column not in base.columns:
            base[column] = pd.NA if column in {"NSI_FD_ID", "NSI_OccType", "NSI_DamageCategory"} else np.nan
    if base.empty or nsi.empty:
        return base

    fields = [
        "fd_id",
        "occtype",
        "st_damcat",
        "num_story",
        "resunits",
        "empnum",
        "students",
        "pop2amu65",
        "pop2amo65",
        "pop2pmu65",
        "pop2pmo65",
        "geometry",
    ]
    for field in fields:
        if field not in nsi.columns and field != "geometry":
            nsi[field] = np.nan
    nsi = nsi[fields].copy()
    for numeric in [
        "num_story",
        "resunits",
        "empnum",
        "students",
        "pop2amu65",
        "pop2amo65",
        "pop2pmu65",
        "pop2pmo65",
    ]:
        nsi[numeric] = to_numeric_safe(nsi[numeric], index=nsi.index)
    nsi["NSI_Pop2AM"] = nsi[["pop2amu65", "pop2amo65"]].sum(axis=1, min_count=1)
    nsi["NSI_Pop2PM"] = nsi[["pop2pmu65", "pop2pmo65"]].sum(axis=1, min_count=1)

    joined = gpd.sjoin(nsi, base[["StructureID", "geometry"]], how="inner", predicate="within")
    if joined.empty:
        return base
    aggregated = joined.groupby("StructureID").agg(
        NSI_FD_ID=("fd_id", _first_value),
        NSI_RecordCount=("fd_id", "count"),
        NSI_OccType=("occtype", _mode_value),
        NSI_DamageCategory=("st_damcat", _mode_value),
        NSI_NumStory=("num_story", "median"),
        NSI_ResUnits=("resunits", _sum_min_count),
        NSI_EmpNum=("empnum", _sum_min_count),
        NSI_Students=("students", _sum_min_count),
        NSI_Pop2AM=("NSI_Pop2AM", _sum_min_count),
        NSI_Pop2PM=("NSI_Pop2PM", _sum_min_count),
    )
    base = base.set_index("StructureID")
    for column in aggregated.columns:
        base[column] = aggregated[column].reindex(base.index).combine_first(base[column])
    return base.reset_index()


def get_acs_household_size(place: pd.Series, config: PipelineConfig) -> tuple[float | None, str | None]:
    if not config.use_census:
        return None, None
    session = requests.Session()
    for year in (2024, 2023, 2022, 2021, 2020):
        params = {
            "get": "NAME,B25010_001E",
            "for": f"place:{place['PlaceFP']}",
            "in": f"state:{place['StateFP']}",
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
        value_i = header.index("B25010_001E")
        value = pd.to_numeric(rows[1][value_i], errors="coerce")
        if pd.notna(value) and value > 0:
            return float(value), f"ACS {year} B25010_001E"
    return None, None


def normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def find_source_column(gdf: gpd.GeoDataFrame, source: dict, canonical_name: str) -> str | None:
    field_map = source.get("field_map", {})
    configured = field_map.get(canonical_name) or field_map.get(canonical_name.lower())
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


def source_for_place(place: pd.Series, config: PipelineConfig, source: dict | str | None) -> dict | None:
    selected = source
    keys = [
        str(place["PlaceGEOID"]),
        slugify(place["City"], place["State"], "USA"),
        slugify(place["City"], place["State"]),
        slugify(place["City"]),
        f"{place['City']}, {place['State']}",
    ]
    for key in keys:
        if selected is None and key in config.parcel_sources:
            selected = config.parcel_sources[key]
    if selected is None:
        return None
    if isinstance(selected, str):
        return {"url": selected} if selected.lower().startswith("http") else {"path": selected}
    return dict(selected)


def read_parcel_source(source: dict, boundary: gpd.GeoDataFrame, config: PipelineConfig) -> gpd.GeoDataFrame:
    if "path" in source:
        path = Path(source["path"]).expanduser()
        if not path.exists():
            LOGGER.warning("Parcels skipped: file not found at %s", path)
            return empty_gdf()
        parcels = gpd.read_parquet(path) if path.suffix.lower() in {".parquet", ".geoparquet"} else gpd.read_file(path)
    elif "url" in source:
        url = source["url"].rstrip("/")
        query_url = url if url.endswith("/query") else f"{url}/query"
        minx, miny, maxx, maxy = bounds_tuple(boundary)
        page_size = int(source.get("page_size", 2000))
        features = []
        offset = 0
        while True:
            params = {
                "f": "geojson",
                "where": source.get("where", "1=1"),
                "outFields": source.get("out_fields", "*"),
                "returnGeometry": "true",
                "geometry": json.dumps(
                    {
                        "xmin": minx,
                        "ymin": miny,
                        "xmax": maxx,
                        "ymax": maxy,
                        "spatialReference": {"wkid": 4326},
                    }
                ),
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "outSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "resultRecordCount": page_size,
                "resultOffset": offset,
            }
            response = requests.get(
                query_url,
                params=params,
                timeout=config.request_timeout_sec,
                verify=certifi.where(),
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("features", [])
            if not batch:
                break
            features.extend(batch)
            offset += len(batch)
            if len(batch) < page_size and not payload.get("exceededTransferLimit"):
                break
        parcels = (
            gpd.GeoDataFrame.from_features(
                {"type": "FeatureCollection", "features": features}, crs="EPSG:4326"
            )
            if features
            else empty_gdf()
        )
    else:
        return empty_gdf()
    if parcels.crs is None:
        parcels = parcels.set_crs(source.get("crs", "EPSG:4326"))
    parcels = clean_geom(parcels.to_crs(epsg=4326))
    if parcels.empty:
        return empty_gdf()

    values = {}
    for canonical in PARCEL_FIELD_ALIASES:
        column = find_source_column(parcels, source, canonical)
        if column:
            values[canonical] = parcels[column]
        elif canonical in PARCEL_TEXT_COLUMNS:
            values[canonical] = pd.Series(pd.NA, index=parcels.index)
        else:
            values[canonical] = pd.Series(np.nan, index=parcels.index)
    out = gpd.GeoDataFrame(values, geometry=parcels.geometry, crs="EPSG:4326")
    out["ParcelSource"] = source.get("name") or source.get("path") or source.get("url")
    return out


def attach_parcel_attributes(
    base: gpd.GeoDataFrame,
    parcels: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    columns = [
        "ParcelID",
        "ParcelAddress",
        "ParcelLandUse",
        "ParcelZoning",
        "ParcelOwner",
        "ParcelAssessedValue",
        "ParcelYearBuilt",
        "ParcelSource",
        "ParcelMatchMethod",
    ]
    for column in columns:
        if column not in base.columns:
            base[column] = pd.NA if column in PARCEL_TEXT_COLUMNS else np.nan
    if base.empty or parcels.empty:
        return base
    points = base[["StructureID", "geometry"]].copy()
    points["geometry"] = points.geometry.representative_point()
    joined = gpd.sjoin(points, parcels[[c for c in columns if c in parcels] + ["geometry"]], how="left", predicate="within")
    joined = joined.drop_duplicates("StructureID").set_index("StructureID")
    base = base.set_index("StructureID")
    for column in columns:
        if column == "ParcelMatchMethod":
            values = pd.Series(pd.NA, index=joined.index)
            values.loc[joined.get("ParcelSource", pd.Series(index=joined.index)).notna()] = "representative_point_within"
        else:
            values = joined.get(column, pd.Series(index=joined.index))
        base[column] = values.reindex(base.index).combine_first(base[column])
    return base.reset_index()


def load_and_attach_parcels(
    base: gpd.GeoDataFrame,
    place: pd.Series,
    boundary: gpd.GeoDataFrame,
    config: PipelineConfig,
    parcel_source: dict | str | None = None,
) -> gpd.GeoDataFrame:
    if not config.use_parcels:
        return base
    source = source_for_place(place, config, parcel_source)
    if source is None:
        return base
    cache_path = config.raw_dir / f"parcels_{place['PlaceGEOID']}.parquet"
    try:
        if source.get("url") and config.cache_remote_parcels and cache_path.exists() and not config.overwrite_raw:
            parcels = gpd.read_parquet(cache_path)
        else:
            parcels = read_parcel_source(source, boundary, config)
            if source.get("url") and config.cache_remote_parcels and not parcels.empty:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                parcels.to_parquet(cache_path, index=False)
    except Exception as exc:
        LOGGER.warning("Parcels skipped for %s: %s", place["PlaceGEOID"], exc)
        return base
    return attach_parcel_attributes(base, parcels)
