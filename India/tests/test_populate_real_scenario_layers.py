import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, box


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from populate_real_scenario_layers import (  # noqa: E402
    SCENARIO_SUFFIXES,
    apply_context_scenarios,
    build_derived_scenario_layers,
    city_slug,
    scenario_id,
)


def one_point_layer() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": ["x"]},
        geometry=[Point(80.2, 13.0)],
        crs="EPSG:4326",
    )


class PopulateRealScenarioLayerTests(unittest.TestCase):
    def test_city_slug_and_scenario_ids(self):
        slug = city_slug("Chennai", "Tamil Nadu", "India")
        self.assertEqual(slug, "chennai_tamil_nadu_india")
        self.assertEqual(len(SCENARIO_SUFFIXES), 6)
        ids = {scenario_id(slug, key) for key in SCENARIO_SUFFIXES}
        self.assertEqual(len(ids), 6)
        self.assertIn(
            "chennai_tamil_nadu_india_transit_oriented_growth_realworld_v1",
            ids,
        )

    def test_context_layers_receive_non_null_scenario(self):
        slug = city_slug("Chennai", "Tamil Nadu", "India")
        transit, water, wetlands = apply_context_scenarios(
            one_point_layer(), one_point_layer(), one_point_layer(), slug
        )
        for layer in (transit, water, wetlands):
            self.assertIn("scenario", layer.columns)
            self.assertTrue(layer["scenario"].notna().all())

    def test_all_six_generated_layers_include_non_null_scenario(self):
        slug = city_slug("Chennai", "Tamil Nadu", "India")
        boundary = gpd.GeoDataFrame(
            geometry=[box(80.1, 12.9, 80.3, 13.1)],
            crs="EPSG:4326",
        )
        transit, water, wetlands = apply_context_scenarios(
            one_point_layer(), one_point_layer(), one_point_layer(), slug
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            structures_path = Path(tmpdir) / "structures.parquet"
            structures = gpd.GeoDataFrame(
                {"StructureID": ["s1"]},
                geometry=[box(80.15, 12.95, 80.151, 12.951)],
                crs="EPSG:4326",
            )
            structures.to_parquet(structures_path, index=False)
            flood, heat, growth = build_derived_scenario_layers(
                boundary=boundary,
                transit=transit,
                water=water,
                wetlands=wetlands,
                structures_path=structures_path,
                city="Chennai",
                state="Tamil Nadu",
                city_slug_value=slug,
            )

        all_layers = [transit, water, wetlands, flood, heat, growth]
        for layer in all_layers:
            self.assertIn("scenario", layer.columns)
            self.assertTrue(layer["scenario"].notna().all())


if __name__ == "__main__":
    unittest.main()
