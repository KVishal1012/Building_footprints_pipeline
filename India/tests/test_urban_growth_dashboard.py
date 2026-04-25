import sys
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from urban_growth_dashboard import (  # noqa: E402
    map_sample,
    mode_column,
    mode_summary,
)


def sample_layers() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "LayerID": ["l1", "l2", "l3"],
            "LayerType": ["planning_context", "urban_planning", "flood_prediction"],
            "SourceName": ["transit", "heat", "flood"],
            "Scenario": ["s1", "s2", "s2"],
            "Score": [0.2, 0.8, 0.5],
        },
        geometry=[Point(80.2, 13.0), Point(80.21, 13.01), Point(80.22, 13.02)],
        crs="EPSG:4326",
    )


def sample_links() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "StructureID": ["st1", "st2", "st2"],
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


if __name__ == "__main__":
    unittest.main()
