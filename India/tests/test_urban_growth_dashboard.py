import sys
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from urban_growth_dashboard import (  # noqa: E402
    ALL_CITIES_LABEL,
    city_readiness,
    filter_by_city,
    filter_by_group,
    latest_run_timestamp,
    link_rate_value,
    map_sample,
    mode_column,
    mode_summary,
    prediction_method_status,
)


def sample_layers() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "LayerID": ["l1", "l2", "l3"],
            "LayerType": ["planning_context", "urban_planning", "flood_prediction"],
            "City": ["Chennai", "Chennai", "Bengaluru"],
            "SourceName": ["transit", "heat", "flood"],
            "Scenario": ["s1", "s2", "s2"],
            "SourceFamily": ["municipal_gis", "heuristic_proxy", "model_export"],
            "ProvenanceTier": ["authoritative", "heuristic", "model"],
            "PredictionKind": [
                "authoritative_context",
                "heuristic_baseline",
                "model_prediction",
            ],
            "ModelFamily": [None, None, None],
            "ModelName": [None, None, None],
            "RunTimestamp": [
                "2026-04-25T10:00:00+00:00",
                "2026-04-25T11:00:00+00:00",
                "2026-04-26T12:00:00+00:00",
            ],
            "Score": [0.2, 0.8, 0.5],
        },
        geometry=[Point(80.2, 13.0), Point(80.21, 13.01), Point(80.22, 13.02)],
        crs="EPSG:4326",
    )


def sample_links() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "StructureID": ["st1", "st2", "st2"],
            "City": ["Chennai", "Chennai", "Bengaluru"],
            "Scenario": ["s1", "s2", "s2"],
            "LayerType": ["planning_context", "urban_planning", "flood_prediction"],
            "SourceName": ["transit", "heat", "flood"],
        }
    )


class UrbanGrowthDashboardModeTests(unittest.TestCase):
    def test_mode_column_mapping(self):
        self.assertEqual(mode_column("Scenario"), "Scenario")
        self.assertEqual(mode_column("LayerType"), "LayerType")
        self.assertEqual(mode_column("SourceName"), "SourceName")

    def test_mode_summary_for_each_mode(self):
        layers = sample_layers()
        links = sample_links()
        for mode in ("Scenario", "LayerType", "SourceName"):
            with self.subTest(mode=mode):
                summary = mode_summary(layers, links, mode)
                self.assertFalse(summary.empty)
                self.assertIn(mode_column(mode), summary.columns)
                self.assertIn("layer_rows", summary.columns)
                self.assertIn("linked_structures", summary.columns)

    def test_map_sample_groups_by_mode(self):
        layers = sample_layers()
        sampled = map_sample(layers, max_features=2, mode="SourceName")
        self.assertLessEqual(len(sampled), 2)
        self.assertIn("lat", sampled.columns)
        self.assertIn("lon", sampled.columns)

    def test_filter_by_city_keeps_selected_city_only(self):
        layers = sample_layers()
        links = sample_links()
        city_layers, city_links = filter_by_city(layers, links, "Chennai")
        self.assertEqual(len(city_layers), 2)
        self.assertEqual(len(city_links), 2)
        self.assertEqual(city_layers["City"].unique().tolist(), ["Chennai"])

    def test_filter_by_city_all_cities_preserves_rows(self):
        layers = sample_layers()
        links = sample_links()
        city_layers, city_links = filter_by_city(layers, links, ALL_CITIES_LABEL)
        self.assertEqual(len(city_layers), len(layers))
        self.assertEqual(len(city_links), len(links))

    def test_filter_by_group_empty_selection_returns_empty_frames(self):
        layers = sample_layers()
        links = sample_links()
        filtered_layers, filtered_links = filter_by_group(layers, links, "Scenario", [])
        self.assertTrue(filtered_layers.empty)
        self.assertTrue(filtered_links.empty)

    def test_city_readiness_counts_city_outputs(self):
        readiness = city_readiness(sample_layers(), sample_links())
        chennai = readiness[readiness["City"] == "Chennai"].iloc[0]
        self.assertEqual(chennai["layer_rows"], 2)
        self.assertEqual(chennai["linked_rows"], 2)
        self.assertEqual(chennai["linked_structures"], 2)
        self.assertEqual(chennai["scenarios"], 2)
        self.assertEqual(chennai["sources"], 2)

    def test_prediction_method_status_defaults_to_heuristic_baseline(self):
        layers = sample_layers().iloc[[1]].copy()
        status = prediction_method_status(layers)
        self.assertEqual(status["active_label"], "Heuristic baseline")
        self.assertFalse(status["is_model_loaded"])
        self.assertIn("not deep-learning predictions", status["active_detail"])

    def test_prediction_method_status_detects_model_outputs(self):
        layers = sample_layers()
        status = prediction_method_status(layers)
        self.assertEqual(status["active_label"], "Model prediction")
        self.assertTrue(status["is_model_loaded"])
        self.assertTrue(status["authoritative_loaded"])

    def test_latest_run_timestamp_formats_utc(self):
        self.assertEqual(latest_run_timestamp(sample_layers()), "2026-04-26 12:00 UTC")

    def test_link_rate_only_uses_all_city_metrics(self):
        self.assertAlmostEqual(
            link_rate_value({"link_rate": 0.25}, ALL_CITIES_LABEL),
            0.25,
        )
        self.assertIsNone(link_rate_value({"link_rate": 0.25}, "Chennai"))
        self.assertIsNone(link_rate_value({}, ALL_CITIES_LABEL))


if __name__ == "__main__":
    unittest.main()
