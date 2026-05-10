from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline_utils import slugify as shared_slugify


SOURCE_FAMILIES = {
    "nrsc_isro",
    "survey_of_india",
    "iudx",
    "municipal_gis",
    "heuristic_proxy",
    "model_export",
    "custom",
}

PROVENANCE_TIERS = {
    "authoritative",
    "model",
    "heuristic",
    "reference",
    "unknown",
}

PREDICTION_KINDS = {
    "authoritative_context",
    "model_prediction",
    "heuristic_baseline",
    "reference",
}

AUTHORITATIVE_SOURCE_FAMILIES = {
    "nrsc_isro",
    "survey_of_india",
    "iudx",
    "municipal_gis",
}

MODEL_SOURCE_FAMILIES = {"model_export"}
HEURISTIC_SOURCE_FAMILIES = {"heuristic_proxy"}

SOURCE_FAMILY_ALIASES = {
    "nrsc": "nrsc_isro",
    "isro": "nrsc_isro",
    "nrsc_isro_bhuvan": "nrsc_isro",
    "survey_of_india_maps": "survey_of_india",
    "soi": "survey_of_india",
    "bbmp_geoportal": "municipal_gis",
    "gcc_gis": "municipal_gis",
    "cmda_gis": "municipal_gis",
    "geoai_model_export": "model_export",
}


def slugify(*parts: str) -> str:
    return shared_slugify(*parts, fallback="custom")


def normalize_source_family(value: object | None) -> str:
    if value is None:
        return "custom"
    slug = slugify(str(value))
    slug = SOURCE_FAMILY_ALIASES.get(slug, slug)
    if slug not in SOURCE_FAMILIES:
        return "custom"
    return slug


def normalize_prediction_kind(value: object | None) -> str | None:
    if value is None:
        return None
    slug = slugify(str(value))
    if slug not in PREDICTION_KINDS:
        raise ValueError(
            f"Unsupported prediction kind {value!r}. Use one of {sorted(PREDICTION_KINDS)}."
        )
    return slug


def normalize_provenance_tier(value: object | None) -> str | None:
    if value is None:
        return None
    slug = slugify(str(value))
    if slug not in PROVENANCE_TIERS:
        raise ValueError(
            f"Unsupported provenance tier {value!r}. Use one of {sorted(PROVENANCE_TIERS)}."
        )
    return slug


def _non_empty(values: Iterable[object | None]) -> list[str]:
    output = []
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text:
            output.append(text)
    return output


def infer_prediction_kind(
    *,
    explicit_kind: object | None = None,
    source_family: object | None = None,
    model_family: object | None = None,
    model_name: object | None = None,
    label: object | None = None,
) -> str:
    normalized = normalize_prediction_kind(explicit_kind)
    if normalized is not None:
        return normalized

    family = normalize_source_family(source_family)
    if family in AUTHORITATIVE_SOURCE_FAMILIES:
        return "authoritative_context"
    if family in MODEL_SOURCE_FAMILIES:
        return "model_prediction"
    if family in HEURISTIC_SOURCE_FAMILIES:
        return "heuristic_baseline"

    model_values = _non_empty([model_family, model_name])
    if model_values:
        return "model_prediction"

    label_text = str(label).lower() if label is not None else ""
    if "authoritative" in label_text or "context" in label_text:
        return "authoritative_context"
    if "reference" in label_text:
        return "reference"
    return "heuristic_baseline"


def default_provenance_tier(*, prediction_kind: object | None = None) -> str:
    kind = normalize_prediction_kind(prediction_kind)
    if kind == "authoritative_context":
        return "authoritative"
    if kind == "model_prediction":
        return "model"
    if kind == "reference":
        return "reference"
    return "heuristic"
