import sys
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from baseline_evaluation import (  # noqa: E402
    EXPECTED_SCENARIO_SUFFIXES,
    build_baseline_evaluation_report,
    model_ready_schema,
    scenario_suffix,
)


def sample_layers() -> gpd.GeoDataFrame:
    chennai_scenarios = [
        f"chennai_tamil_nadu_india_{suffix}"
        for suffix in EXPECTED_SCENARIO_SUFFIXES
    ]
    scenarios = chennai_scenarios + [
        "bengaluru_karnataka_india_transit_oriented_growth_realworld_v1"
    ]
    cities = ["Chennai"] * len(chennai_scenarios) + ["Bengaluru"]
    return gpd.GeoDataFrame(
        {
            "LayerID": [f"l{i}" for i in range(len(scenarios))],
            "LayerType": ["urban_planning"] * len(scenarios),
            "City": cities,
            "State": ["Tamil Nadu"] * len(chennai_scenarios) + ["Karnataka"],
            "Country": ["India"] * len(scenarios),
            "SourceName": ["growth"] * len(scenarios),
            "SourceAuthority": ["derived"] * len(scenarios),
            "SourceFamily": ["heuristic_proxy"] * len(chennai_scenarios)
            + ["model_export"],
            "ProvenanceTier": ["heuristic"] * len(chennai_scenarios) + ["model"],
            "Scenario": scenarios,
            "Label": ["baseline"] * len(scenarios),
            "Score": [0.1, 0.3, 0.4, 0.6, 0.8, 0.9, 0.7],
            "Value": [None] * len(scenarios),
            "PredictionKind": ["heuristic_baseline"] * len(chennai_scenarios)
            + ["model_prediction"],
            "ModelFamily": [None] * len(chennai_scenarios) + ["SegFormer"],
            "ModelName": [None] * len(chennai_scenarios) + ["segformer-v1"],
            "ModelVersion": [None] * len(scenarios),
            "Task": [None] * len(scenarios),
            "RunID": ["run"] * len(scenarios),
            "RunTimestamp": ["2026-04-27T01:00:00+00:00"] * len(scenarios),
        },
        geometry=[Point(80.2 + i / 100, 13.0) for i in range(len(scenarios))],
        crs="EPSG:4326",
    )


def sample_links(layers: gpd.GeoDataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "StructureID": ["s1", "s2", "s3"],
            "City": ["Chennai", "Chennai", "Bengaluru"],
            "Scenario": [
                layers.loc[0, "Scenario"],
                layers.loc[1, "Scenario"],
                layers.loc[6, "Scenario"],
            ],
        }
    )


def sample_structures() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "StructureID": ["s1", "s2", "s3"],
            "City": ["Chennai", "Chennai", "Bengaluru"],
        },
        geometry=[Point(80.2, 13.0), Point(80.21, 13.0), Point(77.6, 12.9)],
        crs="EPSG:4326",
    )


class BaselineEvaluationTests(unittest.TestCase):
    def test_scenario_suffix_detects_expected_suffix(self):
        self.assertEqual(
            scenario_suffix("chennai_tamil_nadu_india_floodplain_lock_in_realworld_v1"),
            "floodplain_lock_in_realworld_v1",
        )
        self.assertIsNone(scenario_suffix("unknown_scenario"))

    def test_report_includes_city_comparison_and_link_rate(self):
        layers = sample_layers()
        report = build_baseline_evaluation_report(
            layers,
            sample_links(layers),
            sample_structures(),
        )

        self.assertEqual(report["prediction_method"], "heuristic_baseline")
        self.assertTrue(report["model_outputs_loaded"])
        self.assertEqual(report["total_layer_rows"], 7)
        self.assertEqual(report["total_link_rows"], 3)
        self.assertAlmostEqual(report["link_rate"], 1.0)
        self.assertEqual(report["rows_by_prediction_kind"]["model_prediction"], 1)

        city_rows = {item["city"]: item for item in report["city_comparison"]}
        self.assertEqual(city_rows["Chennai"]["layer_rows"], 6)
        self.assertAlmostEqual(city_rows["Chennai"]["link_rate"], 1.0)
        self.assertEqual(city_rows["Bengaluru"]["linked_structures"], 1)

    def test_report_tracks_scenario_completeness(self):
        layers = sample_layers()
        report = build_baseline_evaluation_report(layers, sample_links(layers), None)
        completeness = {item["city"]: item for item in report["scenario_completeness"]}

        self.assertTrue(completeness["Chennai"]["complete"])
        self.assertFalse(completeness["Bengaluru"]["complete"])
        self.assertEqual(completeness["Bengaluru"]["present_scenarios"], 1)
        self.assertEqual(len(completeness["Bengaluru"]["missing_scenarios"]), 5)

    def test_model_ready_schema_requires_core_columns_and_crs(self):
        schema = model_ready_schema(sample_layers())
        self.assertTrue(schema["ready"])
        self.assertEqual(schema["missing_required_columns"], [])
        self.assertEqual(schema["geometry_crs"], "EPSG:4326")

        missing_score = sample_layers().drop(columns=["Score"])
        schema = model_ready_schema(missing_score)
        self.assertFalse(schema["ready"])
        self.assertIn("Score", schema["missing_required_columns"])


if __name__ == "__main__":
    unittest.main()
