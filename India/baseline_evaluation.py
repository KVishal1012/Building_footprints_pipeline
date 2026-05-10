from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from processing_semantics import infer_prediction_kind


MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_LAYERS_PATH = MODULE_DIR / "data/processing/output/processing_layers.parquet"
DEFAULT_LINKS_PATH = MODULE_DIR / "data/processing/output/structure_processing_links.parquet"

EVALUATION_PROFILE = "heuristic_baseline_v1"
PREDICTION_METHOD = "heuristic_baseline"

EXPECTED_SCENARIO_SUFFIXES = [
    "transit_oriented_growth_realworld_v1",
    "blue_green_network_protection_realworld_v1",
    "wetland_edge_encroachment_realworld_v1",
    "floodplain_lock_in_realworld_v1",
    "heat_island_intensification_corridor_realworld_v1",
    "compound_risk_growth_hotspots_realworld_v1",
]

MODEL_READY_REQUIRED_COLUMNS = [
    "LayerID",
    "LayerType",
    "City",
    "State",
    "Country",
    "SourceName",
    "SourceAuthority",
    "Scenario",
    "Label",
    "Score",
    "Value",
    "geometry",
]

MODEL_PROVENANCE_COLUMNS = [
    "ModelFamily",
    "ModelName",
    "ModelVersion",
    "Task",
    "RunID",
    "RunTimestamp",
]


def _maybe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    return {
        str(key): int(value)
        for key, value in frame[column].value_counts(dropna=False).items()
    }


def prediction_kind_series(frame: pd.DataFrame) -> pd.Series:
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


def _score_distribution(frame: pd.DataFrame) -> dict[str, float | int | None]:
    if frame.empty or "Score" not in frame.columns:
        return {
            "rows": int(len(frame)),
            "scored_rows": 0,
            "null_rate": None,
            "min": None,
            "p10": None,
            "mean": None,
            "median": None,
            "p90": None,
            "max": None,
        }
    scores = pd.to_numeric(frame["Score"], errors="coerce")
    scored = scores.dropna()
    null_rate = float(scores.isna().mean()) if len(scores) else None
    if scored.empty:
        return {
            "rows": int(len(frame)),
            "scored_rows": 0,
            "null_rate": null_rate,
            "min": None,
            "p10": None,
            "mean": None,
            "median": None,
            "p90": None,
            "max": None,
        }
    return {
        "rows": int(len(frame)),
        "scored_rows": int(len(scored)),
        "null_rate": null_rate,
        "min": _maybe_float(scored.min()),
        "p10": _maybe_float(scored.quantile(0.10)),
        "mean": _maybe_float(scored.mean()),
        "median": _maybe_float(scored.median()),
        "p90": _maybe_float(scored.quantile(0.90)),
        "max": _maybe_float(scored.max()),
    }


def _non_empty_unique(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame.columns:
        return []
    values = frame[column].dropna().astype("string").str.strip()
    return sorted(value for value in values.unique().tolist() if value)


def model_outputs_loaded(layers: pd.DataFrame) -> bool:
    kinds = set(prediction_kind_series(layers).dropna().astype("string").tolist())
    return "model_prediction" in kinds


def scenario_suffix(scenario: object) -> str | None:
    scenario_text = str(scenario)
    for suffix in EXPECTED_SCENARIO_SUFFIXES:
        if scenario_text.endswith(suffix):
            return suffix
    return None


def _filter_city(frame: pd.DataFrame, city: str) -> pd.DataFrame:
    if frame.empty or "City" not in frame.columns:
        return frame
    return frame[frame["City"].astype("string") == city]


def _filter_scenario(frame: pd.DataFrame, scenario: object) -> pd.DataFrame:
    if frame.empty or "Scenario" not in frame.columns:
        return frame.iloc[0:0]
    return frame[frame["Scenario"].astype("string") == str(scenario)]


def _structure_denominator(
    structures: pd.DataFrame | None, city: str | None = None
) -> int | None:
    if structures is None:
        return None
    if city is not None and "City" in structures.columns:
        return int(len(_filter_city(structures, city)))
    return int(len(structures))


def _link_rate(unique_linked_structures: int, denominator: int | None) -> float | None:
    if denominator is None or denominator <= 0:
        return None
    return float(unique_linked_structures / denominator)


def city_comparison(
    layers: pd.DataFrame, links: pd.DataFrame, structures: pd.DataFrame | None
) -> list[dict[str, Any]]:
    if layers.empty or "City" not in layers.columns:
        return []
    cities = sorted(layers["City"].dropna().astype("string").unique().tolist())
    output = []
    total_rows = max(int(len(layers)), 1)
    total_linked = max(int(links["StructureID"].nunique()) if not links.empty else 0, 1)
    for city in cities:
        city_layers = _filter_city(layers, city)
        city_links = _filter_city(links, city)
        linked_structures = (
            int(city_links["StructureID"].nunique())
            if not city_links.empty and "StructureID" in city_links.columns
            else 0
        )
        denominator = _structure_denominator(structures, city)
        output.append(
            {
                "city": city,
                "layer_rows": int(len(city_layers)),
                "row_share": float(len(city_layers) / total_rows),
                "link_rows": int(len(city_links)),
                "linked_structures": linked_structures,
                "linked_structure_share": float(linked_structures / total_linked),
                "structure_denominator": denominator,
                "link_rate": _link_rate(linked_structures, denominator),
                "scenario_count": int(city_layers["Scenario"].nunique()),
                "source_count": int(city_layers["SourceName"].nunique()),
                "score_distribution": _score_distribution(city_layers),
            }
        )
    return output


def scenario_completeness(layers: pd.DataFrame) -> list[dict[str, Any]]:
    if layers.empty or "City" not in layers.columns or "Scenario" not in layers.columns:
        return []
    output = []
    for city, city_layers in layers.groupby("City", dropna=False):
        present_suffixes = sorted(
            suffix
            for suffix in {
                scenario_suffix(value)
                for value in city_layers["Scenario"].dropna().astype("string").unique()
            }
            if suffix is not None
        )
        missing_suffixes = [
            suffix for suffix in EXPECTED_SCENARIO_SUFFIXES if suffix not in present_suffixes
        ]
        output.append(
            {
                "city": str(city),
                "expected_scenarios": len(EXPECTED_SCENARIO_SUFFIXES),
                "present_scenarios": len(present_suffixes),
                "missing_scenarios": missing_suffixes,
                "complete": not missing_suffixes,
            }
        )
    return sorted(output, key=lambda item: item["city"])


def scenario_summaries(
    layers: pd.DataFrame, links: pd.DataFrame, structures: pd.DataFrame | None
) -> list[dict[str, Any]]:
    if layers.empty or "Scenario" not in layers.columns:
        return []
    group_columns = ["Scenario"]
    if "City" in layers.columns:
        group_columns = ["City", "Scenario"]
    output = []
    for group_key, scenario_layers in layers.groupby(group_columns, dropna=False):
        if isinstance(group_key, tuple):
            city, scenario = group_key
        else:
            city, scenario = None, group_key
        scenario_links = _filter_scenario(links, scenario)
        if city is not None:
            scenario_links = _filter_city(scenario_links, str(city))
        linked_structures = (
            int(scenario_links["StructureID"].nunique())
            if not scenario_links.empty and "StructureID" in scenario_links.columns
            else 0
        )
        denominator = _structure_denominator(structures, str(city) if city is not None else None)
        output.append(
            {
                "city": str(city) if city is not None else None,
                "scenario": str(scenario),
                "scenario_suffix": scenario_suffix(scenario),
                "layer_rows": int(len(scenario_layers)),
                "link_rows": int(len(scenario_links)),
                "linked_structures": linked_structures,
                "structure_denominator": denominator,
                "link_rate": _link_rate(linked_structures, denominator),
                "layer_types": _value_counts(scenario_layers, "LayerType"),
                "sources": _value_counts(scenario_layers, "SourceName"),
                "score_distribution": _score_distribution(scenario_layers),
            }
        )
    return sorted(output, key=lambda item: (item["city"] or "", item["scenario"]))


def model_ready_schema(layers: pd.DataFrame) -> dict[str, Any]:
    columns = set(layers.columns)
    required_missing = [
        column for column in MODEL_READY_REQUIRED_COLUMNS if column not in columns
    ]
    provenance_missing = [
        column for column in MODEL_PROVENANCE_COLUMNS if column not in columns
    ]
    crs = getattr(layers, "crs", None)
    return {
        "required_columns": MODEL_READY_REQUIRED_COLUMNS,
        "missing_required_columns": required_missing,
        "provenance_columns": MODEL_PROVENANCE_COLUMNS,
        "missing_provenance_columns": provenance_missing,
        "geometry_crs": str(crs) if crs else None,
        "ready": not required_missing and crs is not None,
    }


def build_baseline_evaluation_report(
    layers: gpd.GeoDataFrame,
    links: pd.DataFrame,
    structures: pd.DataFrame | None = None,
) -> dict[str, Any]:
    unique_linked_structures = (
        int(links["StructureID"].nunique())
        if not links.empty and "StructureID" in links.columns
        else 0
    )
    total_structures = _structure_denominator(structures)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_profile": EVALUATION_PROFILE,
        "prediction_method": PREDICTION_METHOD,
        "model_outputs_loaded": model_outputs_loaded(layers),
        "total_layer_rows": int(len(layers)),
        "total_link_rows": int(len(links)),
        "unique_linked_structures": unique_linked_structures,
        "total_structures": total_structures,
        "link_rate": _link_rate(unique_linked_structures, total_structures),
        "rows_by_city": _value_counts(layers, "City"),
        "rows_by_layer_type": _value_counts(layers, "LayerType"),
        "rows_by_source_name": _value_counts(layers, "SourceName"),
        "rows_by_source_family": _value_counts(layers, "SourceFamily"),
        "rows_by_provenance_tier": _value_counts(layers, "ProvenanceTier"),
        "rows_by_prediction_kind": {
            str(key): int(value)
            for key, value in prediction_kind_series(layers).value_counts(dropna=False).items()
        },
        "rows_by_scenario": _value_counts(layers, "Scenario"),
        "score_distribution": _score_distribution(layers),
        "city_comparison": city_comparison(layers, links, structures),
        "scenario_completeness": scenario_completeness(layers),
        "scenario_summaries": scenario_summaries(layers, links, structures),
        "model_ready_schema": model_ready_schema(layers),
    }


def read_inputs(
    layers_path: Path, links_path: Path, structures_path: Path | None
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, gpd.GeoDataFrame | None]:
    if not layers_path.exists():
        raise FileNotFoundError(f"Missing layers parquet: {layers_path}")
    if not links_path.exists():
        raise FileNotFoundError(f"Missing links parquet: {links_path}")
    structures = None
    if structures_path is not None:
        if not structures_path.exists():
            raise FileNotFoundError(f"Missing structures parquet: {structures_path}")
        structures = gpd.read_parquet(structures_path)
    return gpd.read_parquet(layers_path), pd.read_parquet(links_path), structures


def write_report(report: dict[str, Any], output_path: Path | None) -> None:
    payload = json.dumps(report, indent=2, default=str) + "\n"
    if output_path is None:
        print(payload, end="")
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload)
    print(f"Wrote baseline evaluation report to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate heuristic baseline scenario outputs for dashboard/model readiness."
    )
    parser.add_argument("--layers-path", type=Path, default=DEFAULT_LAYERS_PATH)
    parser.add_argument("--links-path", type=Path, default=DEFAULT_LINKS_PATH)
    parser.add_argument(
        "--structures-path",
        type=Path,
        default=None,
        help="Optional structures parquet for true link-rate denominators.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional JSON report path. If omitted, the report prints to stdout.",
    )
    args = parser.parse_args()

    layers, links, structures = read_inputs(
        args.layers_path, args.links_path, args.structures_path
    )
    report = build_baseline_evaluation_report(layers, links, structures)
    write_report(report, args.output_json)


if __name__ == "__main__":
    main()
