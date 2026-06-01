from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from processing_semantics import SOURCE_FAMILIES, infer_prediction_kind


REQUIRED_PROVENANCE_COLUMNS = [
    "SourceAuthority",
    "SourceFamily",
    "ProvenanceTier",
    "PredictionKind",
    "Scenario",
    "RunID",
    "City",
    "State",
    "geometry",
]


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    """Resolve config paths while supporting repo-root-prefixed India paths."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "India":
        return (REPO_ROOT / path).resolve()
    return (base_dir / path).resolve()


def _scenario_suffixes(series: pd.Series) -> set[str]:
    """Return normalized non-empty scenario identifiers from an output column."""
    return {
        str(value).strip()
        for value in series.dropna().astype("string").tolist()
        if str(value).strip()
    }


def _prediction_kind_series(frame: pd.DataFrame) -> pd.Series:
    """Return explicit prediction kinds, inferring values for older outputs."""
    if frame.empty:
        return pd.Series(dtype="string")
    if "PredictionKind" in frame.columns:
        return frame["PredictionKind"].astype("string").fillna("heuristic_baseline")
    return pd.Series(
        [
            infer_prediction_kind(
                explicit_kind=None,
                source_family=frame.iloc[i]["SourceFamily"] if "SourceFamily" in frame.columns else None,
                model_family=frame.iloc[i]["ModelFamily"] if "ModelFamily" in frame.columns else None,
                model_name=frame.iloc[i]["ModelName"] if "ModelName" in frame.columns else None,
                label=frame.iloc[i]["SourceName"] if "SourceName" in frame.columns else None,
            )
            for i in range(len(frame))
        ],
        index=frame.index,
        dtype="string",
    )


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    """Return JSON-safe value counts for a report dimension."""
    if frame.empty or column not in frame.columns:
        return {}
    return {
        str(key): int(value)
        for key, value in frame[column].value_counts(dropna=False).items()
    }


def _blank_mask(series: pd.Series) -> pd.Series:
    """Mark null and whitespace-only provenance values as incomplete."""
    return series.isna() | series.astype("string").str.strip().fillna("").eq("")


@dataclass
class AuthoritativeSourceRule:
    """Describe an authoritative source that must be present before release."""

    source_name: str
    min_rows: int = 1
    accepted_prediction_kinds: list[str] = field(
        default_factory=lambda: ["authoritative_context"]
    )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoritativeSourceRule":
        """Build one required-source rule from verification config JSON."""
        source_name = str(payload.get("source_name", "")).strip()
        if not source_name:
            raise ValueError("authoritative_sources entries require source_name")
        return cls(
            source_name=source_name,
            min_rows=int(payload.get("min_rows", 1)),
            accepted_prediction_kinds=[
                str(value)
                for value in payload.get(
                    "accepted_prediction_kinds", ["authoritative_context"]
                )
            ],
        )


@dataclass
class CityVerificationRule:
    """Collect release thresholds and required layers for one city."""

    min_link_rate: float = 0.0
    required_scenarios: list[str] = field(default_factory=list)
    min_authoritative_rows: int = 0
    min_model_rows: int = 0
    authoritative_sources: list[AuthoritativeSourceRule] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CityVerificationRule":
        """Build one city verification rule from config JSON."""
        return cls(
            min_link_rate=float(payload.get("min_link_rate", 0.0)),
            required_scenarios=[str(value) for value in payload.get("required_scenarios", [])],
            min_authoritative_rows=int(payload.get("min_authoritative_rows", 0)),
            min_model_rows=int(payload.get("min_model_rows", 0)),
            authoritative_sources=[
                AuthoritativeSourceRule.from_dict(value)
                for value in payload.get("authoritative_sources", [])
            ],
        )


@dataclass
class VerificationConfig:
    """Define output paths and strict production gates for a release run."""

    structure_path: Path
    layers_path: Path
    links_path: Path
    metrics_path: Path
    require_metadata_sidecars: bool = True
    strict_source_families: bool = True
    cities: dict[str, CityVerificationRule] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: Path) -> "VerificationConfig":
        """Load and validate a verification configuration document."""
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("Verification config must be a JSON object")
        base_dir = path.parent
        cities_payload = payload.get("cities", {})
        if not isinstance(cities_payload, dict):
            raise ValueError("'cities' must be a JSON object")
        return cls(
            structure_path=_resolve_path(
                payload.get("structure_path", "India/data/output/structures_master.parquet"),
                base_dir,
            ),
            layers_path=_resolve_path(
                payload.get(
                    "layers_path", "India/data/processing/output/processing_layers.parquet"
                ),
                base_dir,
            ),
            links_path=_resolve_path(
                payload.get(
                    "links_path",
                    "India/data/processing/output/structure_processing_links.parquet",
                ),
                base_dir,
            ),
            metrics_path=_resolve_path(
                payload.get(
                    "metrics_path", "India/data/processing/output/processing_metrics.json"
                ),
                base_dir,
            ),
            require_metadata_sidecars=bool(payload.get("require_metadata_sidecars", True)),
            strict_source_families=bool(payload.get("strict_source_families", True)),
            cities={
                str(city): CityVerificationRule.from_dict(rule)
                for city, rule in cities_payload.items()
            },
        )


def _metadata_sidecar(path: Path) -> Path:
    """Return the metadata sidecar path emitted beside a parquet output."""
    return Path(f"{path}.metadata.json")


def _validate_metadata(path: Path, errors: list[str]) -> None:
    """Require an output and its metadata sidecar for promoted releases."""
    if not path.exists():
        errors.append(f"Missing required file: {path}")
        return
    sidecar = _metadata_sidecar(path)
    if not sidecar.exists():
        errors.append(f"Missing metadata sidecar: {sidecar}")


def _validate_geometries(frame: gpd.GeoDataFrame, label: str, errors: list[str]) -> None:
    """Reject missing, null, empty, or invalid output geometries."""
    if getattr(frame, "geometry", None) is None:
        errors.append(f"{label} parquet is missing geometry")
        return
    invalid_mask = frame.geometry.isna() | frame.geometry.is_empty | ~frame.geometry.is_valid
    if invalid_mask.any():
        errors.append(f"{label} parquet contains null, empty, or invalid geometries")


def _validate_provenance(
    layers: gpd.GeoDataFrame, config: VerificationConfig, errors: list[str]
) -> None:
    """Require complete semantic provenance and known source families."""
    missing_columns = [
        column for column in REQUIRED_PROVENANCE_COLUMNS if column not in layers.columns
    ]
    if missing_columns:
        errors.append(f"processing layers are missing provenance columns: {missing_columns}")
        return
    for column in REQUIRED_PROVENANCE_COLUMNS:
        if column == "geometry":
            continue
        blank_rows = int(_blank_mask(layers[column]).sum())
        if blank_rows:
            errors.append(f"processing layers contain {blank_rows} blank {column} values")
    if config.strict_source_families:
        invalid_families = sorted(
            {
                str(value)
                for value in layers["SourceFamily"].dropna().astype("string")
                if str(value) not in SOURCE_FAMILIES or str(value) == "custom"
            }
        )
        if invalid_families:
            errors.append(
                "processing layers contain unsupported strict-mode SourceFamily values: "
                f"{invalid_families}"
            )


def _validate_link_targets(
    structures: gpd.GeoDataFrame, links: pd.DataFrame, errors: list[str]
) -> None:
    """Reject links that reference structure identifiers absent from canonical output."""
    if "StructureID" not in links.columns:
        errors.append("structure-processing links parquet is missing StructureID")
        return
    if "StructureID" not in structures.columns:
        return
    known_ids = set(structures["StructureID"].dropna().astype("string"))
    linked_ids = set(links["StructureID"].dropna().astype("string"))
    missing_ids = linked_ids - known_ids
    if missing_ids:
        errors.append(
            f"structure-processing links contain {len(missing_ids)} unknown StructureID values"
        )


def _city_link_rate(
    structures: gpd.GeoDataFrame, links: pd.DataFrame, city: str
) -> tuple[int, int, float]:
    """Calculate canonical structure count and linked-structure coverage for a city."""
    city_structures = (
        structures[structures["City"].astype("string") == city]
        if "City" in structures.columns
        else structures.iloc[0:0]
    )
    city_links = (
        links[links["City"].astype("string") == city]
        if "City" in links.columns
        else links.iloc[0:0]
    )
    structure_count = int(len(city_structures))
    unique_linked = (
        int(city_links["StructureID"].nunique())
        if not city_links.empty and "StructureID" in city_links.columns
        else 0
    )
    link_rate = float(unique_linked / structure_count) if structure_count else 0.0
    return structure_count, unique_linked, link_rate


def calibrate_thresholds(config: VerificationConfig) -> dict[str, Any]:
    """Recommend deterministic per-city link-rate gates without mutating config."""
    for required_path in (config.structure_path, config.links_path):
        if not required_path.exists():
            raise FileNotFoundError(f"Missing required file: {required_path}")
    structures = gpd.read_parquet(config.structure_path)
    links = pd.read_parquet(config.links_path)
    cities = {}
    for city in config.cities:
        structure_count, unique_linked, measured_link_rate = _city_link_rate(
            structures, links, city
        )
        cities[city] = {
            "structure_count": structure_count,
            "unique_linked_structures": unique_linked,
            "measured_link_rate": measured_link_rate,
            "recommended_min_link_rate": max(0.0005, measured_link_rate * 0.90),
        }
    return {"formula": "max(0.0005, measured_link_rate * 0.90)", "cities": cities}


def verify_outputs(config: VerificationConfig) -> dict[str, Any]:
    """Verify canonical and processing outputs against promotion gates."""
    errors: list[str] = []
    if config.require_metadata_sidecars:
        for path in (config.structure_path, config.layers_path, config.links_path):
            _validate_metadata(path, errors)

    for required_path in (
        config.structure_path,
        config.layers_path,
        config.links_path,
        config.metrics_path,
    ):
        if not required_path.exists():
            errors.append(f"Missing required file: {required_path}")

    if errors:
        return {"passed": False, "errors": errors, "city_results": []}

    structures = gpd.read_parquet(config.structure_path)
    layers = gpd.read_parquet(config.layers_path)
    links = pd.read_parquet(config.links_path)
    metrics = json.loads(config.metrics_path.read_text())

    if "StructureID" not in structures.columns:
        errors.append("structures parquet is missing StructureID")
    elif structures["StructureID"].duplicated().any():
        errors.append("structures parquet contains duplicate StructureID values")

    _validate_geometries(structures, "structures", errors)
    _validate_geometries(layers, "processing layers", errors)
    _validate_provenance(layers, config, errors)
    _validate_link_targets(structures, links, errors)

    city_results = []
    if not layers.empty:
        prediction_kinds = _prediction_kind_series(layers)
        layers = layers.copy()
        layers["PredictionKind"] = prediction_kinds

    for city, rule in config.cities.items():
        city_structures = (
            structures[structures["City"].astype("string") == city].copy()
            if "City" in structures.columns
            else structures.iloc[0:0].copy()
        )
        city_layers = (
            layers[layers["City"].astype("string") == city].copy()
            if "City" in layers.columns
            else layers.iloc[0:0].copy()
        )
        city_links = (
            links[links["City"].astype("string") == city].copy()
            if "City" in links.columns
            else links.iloc[0:0].copy()
        )
        structure_count, unique_linked, link_rate = _city_link_rate(
            structures, links, city
        )
        city_scenarios = _scenario_suffixes(city_layers["Scenario"]) if "Scenario" in city_layers.columns else set()
        missing_scenarios = [
            scenario for scenario in rule.required_scenarios if scenario not in city_scenarios
        ]
        authoritative_rows = (
            int((city_layers["PredictionKind"] == "authoritative_context").sum())
            if "PredictionKind" in city_layers.columns
            else 0
        )
        model_rows = (
            int((city_layers["PredictionKind"] == "model_prediction").sum())
            if "PredictionKind" in city_layers.columns
            else 0
        )
        city_errors = []
        authoritative_source_results = []
        if link_rate < rule.min_link_rate:
            city_errors.append(
                f"{city}: link_rate {link_rate:.2%} is below minimum {rule.min_link_rate:.2%}"
            )
        if missing_scenarios:
            city_errors.append(f"{city}: missing required scenarios {missing_scenarios}")
        if authoritative_rows < rule.min_authoritative_rows:
            city_errors.append(
                f"{city}: authoritative rows {authoritative_rows} below minimum {rule.min_authoritative_rows}"
            )
        if model_rows < rule.min_model_rows:
            city_errors.append(f"{city}: model rows {model_rows} below minimum {rule.min_model_rows}")
        for source_rule in rule.authoritative_sources:
            source_rows = city_layers[
                (city_layers["SourceName"].astype("string") == source_rule.source_name)
                & city_layers["PredictionKind"].astype("string").isin(
                    source_rule.accepted_prediction_kinds
                )
            ]
            source_row_count = int(len(source_rows))
            if source_row_count < source_rule.min_rows:
                city_errors.append(
                    f"{city}: source {source_rule.source_name!r} rows {source_row_count} "
                    f"below minimum {source_rule.min_rows}"
                )
            authoritative_source_results.append(
                {
                    "source_name": source_rule.source_name,
                    "rows": source_row_count,
                    "min_rows": source_rule.min_rows,
                    "accepted_prediction_kinds": source_rule.accepted_prediction_kinds,
                }
            )
        errors.extend(city_errors)
        city_results.append(
            {
                "city": city,
                "structure_count": structure_count,
                "unique_linked_structures": unique_linked,
                "link_rate": link_rate,
                "layer_rows": int(len(city_layers)),
                "authoritative_rows": authoritative_rows,
                "model_rows": model_rows,
                "missing_scenarios": missing_scenarios,
                "authoritative_sources": authoritative_source_results,
                "passed": not city_errors,
            }
        )

    return {
        "passed": not errors,
        "errors": errors,
        "city_results": city_results,
        "metrics_summary": {
            "total_layer_rows": metrics.get("total_layer_rows"),
            "total_links": metrics.get("total_links"),
            "link_rate": metrics.get("link_rate"),
            "rows_by_prediction_kind": metrics.get("rows_by_prediction_kind", {}),
            "rows_by_city": _value_counts(layers, "City"),
            "rows_by_scenario": _value_counts(layers, "Scenario"),
            "rows_by_source_family": _value_counts(layers, "SourceFamily"),
            "rows_by_provenance_tier": _value_counts(layers, "ProvenanceTier"),
            "rows_by_prediction_kind_verified": _value_counts(layers, "PredictionKind"),
        },
    }


def main() -> None:
    """Run verification or write a report-only threshold calibration document."""
    parser = argparse.ArgumentParser(
        description="Verify India multi-city processing outputs against production thresholds."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=MODULE_DIR / "production_verification.example.json",
        help="JSON verification config with per-city thresholds.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write the verification report.",
    )
    parser.add_argument(
        "--calibrate-thresholds",
        action="store_true",
        help="Write recommended city link-rate thresholds from existing outputs.",
    )
    args = parser.parse_args()

    config = VerificationConfig.from_json(args.config)
    report = calibrate_thresholds(config) if args.calibrate_thresholds else verify_outputs(config)
    payload = json.dumps(report, indent=2) + "\n"
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(payload)
    print(payload, end="")
    if not args.calibrate_thresholds and not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
