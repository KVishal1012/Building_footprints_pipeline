from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from structures_pipeline.constants import STATE_ABBR_TO_NAME, STATE_FIPS, STATE_NAME_TO_ABBR


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(*parts: str) -> str:
    text = "_".join(str(part) for part in parts if part)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "place"


def normalize_state_name(state: str) -> str:
    stripped = state.strip()
    if len(stripped) == 2 and stripped.upper() in STATE_ABBR_TO_NAME:
        return STATE_ABBR_TO_NAME[stripped.upper()]
    return stripped


def statefp_for_state(state: str) -> str:
    name = normalize_state_name(state).lower()
    if name not in STATE_FIPS:
        raise ValueError(f"Unsupported state for v1 US pipeline: {state}")
    return STATE_FIPS[name]


def state_abbr_for_state(state: str) -> str:
    name = normalize_state_name(state).lower()
    if name not in STATE_NAME_TO_ABBR:
        raise ValueError(f"Unsupported state for v1 US pipeline: {state}")
    return STATE_NAME_TO_ABBR[name]


def normalize_place_name(value: str) -> str:
    text = str(value).lower()
    text = re.sub(r"\b(city|town|village|borough|municipality|cdp)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text


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
        if match.group(2) in {"ft", "feet", "'"}:
            number *= 0.3048
        return number

    return series.apply(_parse)


def json_safe(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(json_safe(item) for item in value)
    return value


def stable_hash(value, length: int = 12) -> str:
    payload = json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:length]


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


def confidence_for_source(source: pd.Series, mapping: dict[str, float]) -> pd.Series:
    return source.map(mapping).astype("float64")
