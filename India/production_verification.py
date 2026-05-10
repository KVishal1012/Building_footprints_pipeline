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

from processing_semantics import infer_prediction_kind


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _scenario_suffixes(series: pd.Series) -> set[str]:
    return {
        str(value).strip()
        for value in series.dropna().astype("string").tolist()
        if str(value).strip()
    }


def _prediction_kind_series(frame: pd.DataFrame) -> pd.Series:
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


@dataclass
class CityVerificationRule:
    min_link_rate: float = 0.0
    required_scenarios: list[str] = field(default_factory=list)
    min_authoritative_rows: int = 0
    min_model_rows: int = 0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CityVerificationRule":
        return cls(
            min_link_rate=float(payload.get("min_link_rate", 0.0)),
            required_scenarios=[str(value) for value in payload.get("required_scenarios", [])],
            min_authoritative_rows=int(payload.get("min_authoritative_rows", 0)),
            min_model_rows=int(payload.get("min_model_rows", 0)),
        )


@dataclass
class VerificationConfig:
    structure_path: Path
    layers_path: Path
    links_path: Path
    metrics_path: Path
    require_metadata_sidecars: bool = True
    cities: dict[str, CityVerificationRule] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: Path) -> "VerificationConfig":
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
            cities={
                str(city): CityVerificationRule.from_dict(rule)
                for city, rule in cities_payload.items()
            },
        )


def _metadata_sidecar(path: Path) -> Path:
    return Path(f"{path}.metadata.json")


def _validate_metadata(path: Path, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"Missing required file: {path}")
        return
    sidecar = _metadata_sidecar(path)
    if not sidecar.exists():
        errors.append(f"Missing metadata sidecar: {sidecar}")


def verify_outputs(config: VerificationConfig) -> dict[str, Any]:
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

    if getattr(structures, "geometry", None) is None:
        errors.append("structures parquet is missing geometry")
    else:
        invalid_mask = structures.geometry.isna() | structures.geometry.is_empty | ~structures.geometry.is_valid
        if invalid_mask.any():
            errors.append("structures parquet contains null, empty, or invalid geometries")

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
        structure_count = int(len(city_structures))
        unique_linked = (
            int(city_links["StructureID"].nunique())
            if not city_links.empty and "StructureID" in city_links.columns
            else 0
        )
        link_rate = float(unique_linked / structure_count) if structure_count > 0 else 0.0
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
        },
    }


def main() -> None:
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
    args = parser.parse_args()

    report = verify_outputs(VerificationConfig.from_json(args.config))
    payload = json.dumps(report, indent=2) + "\n"
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(payload)
    print(payload, end="")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
