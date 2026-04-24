from __future__ import annotations

import json
import re
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import make_valid
from shapely.geometry import MultiPolygon


def slugify(*parts: str, fallback: str = "place") -> str:
    text = "_".join(str(part) for part in parts if part)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or fallback


def normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def normalize_alias_name(
    value: str | None,
    aliases: dict[str, str],
    *,
    collapse_alias_key: bool = False,
) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    alias_key = stripped.upper()
    if collapse_alias_key:
        alias_key = re.sub(r"[^A-Za-z0-9]+", "", stripped).upper()
    return aliases.get(alias_key, stripped)


def resolve_source_path(
    path_value: str | Path,
    candidates: Iterable[Path],
    *,
    fallback: Path | None = None,
) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path

    candidates = list(candidates)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if fallback is not None:
        return fallback
    return candidates[0] if candidates else path


def source_failure(
    message: str,
    *,
    strict: bool = False,
    exc: Exception | None = None,
) -> None:
    if strict:
        raise RuntimeError(message) from exc
    print(message)


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


def clean_geometry(
    gdf: gpd.GeoDataFrame,
    *,
    polygonal_only: bool = False,
    validate_all: bool = False,
) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    geometry_column = gdf.geometry.name
    cleaned = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if cleaned.empty:
        return cleaned

    invalid = pd.Series(validate_all, index=cleaned.index)
    if not validate_all:
        invalid = ~cleaned.geometry.is_valid
    if invalid.any():
        cleaned.loc[invalid, geometry_column] = cleaned.loc[
            invalid, geometry_column
        ].apply(make_valid)

    if polygonal_only:
        polygon_types = {"Polygon", "MultiPolygon"}
        cleaned[geometry_column] = cleaned.geometry.apply(polygonal_part)
        cleaned = cleaned[
            cleaned.geometry.notna()
            & ~cleaned.geometry.is_empty
            & cleaned.geometry.is_valid
            & cleaned.geometry.geom_type.isin(polygon_types)
        ].copy()
    else:
        cleaned = cleaned[~cleaned.geometry.is_empty].copy()
    return cleaned


def estimated_projected_crs(*gdfs: gpd.GeoDataFrame, fallback: str = "EPSG:6933"):
    for gdf in gdfs:
        if gdf is not None and not gdf.empty:
            crs = gdf.estimate_utm_crs()
            if crs is not None:
                return crs
    return fallback


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


def config_metadata(config) -> dict:
    if not is_dataclass(config):
        raise TypeError("config_metadata expects a dataclass instance")
    return {field.name: json_safe(getattr(config, field.name)) for field in fields(config)}


def write_metadata_sidecar(
    output_path: Path,
    config,
    metadata: dict,
    *,
    include_config: bool = True,
    trailing_newline: bool = True,
) -> None:
    if not getattr(config, "write_run_metadata", False):
        return
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }
    if include_config:
        payload["config"] = config_metadata(config)
    suffix = output_path.suffix + ".metadata.json"
    sidecar_path = output_path.with_suffix(suffix)
    text = json.dumps(json_safe(payload), indent=2)
    if trailing_newline:
        text += "\n"
    sidecar_path.write_text(text)
