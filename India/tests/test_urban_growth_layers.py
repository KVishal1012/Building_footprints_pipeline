import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from urban_growth_layers import (  # noqa: E402
    OUTPUT_COLUMNS,
    SCENARIOS,
    build_urban_growth_layers,
    write_urban_growth_layers,
)


def sample_structures() -> gpd.GeoDataFrame:
    records = []
    geometries = []
    for i in range(10):
        for j in range(10):
            records.append({"StructureID": f"s_{i}_{j}"})
            x = 80.15 + i * 0.01
            y = 12.90 + j * 0.01
            geometries.append(box(x, y, x + 0.002, y + 0.002))
    return gpd.GeoDataFrame(records, geometry=geometries, crs="EPSG:4326")


class UrbanGrowthLayerTests(unittest.TestCase):
    def test_builds_all_priority_scenarios(self):
        layers = build_urban_growth_layers(sample_structures())

        self.assertEqual(set(layers), {scenario.slug for scenario in SCENARIOS})
        self.assertEqual(len(layers), 7)

    def test_layers_have_required_columns_and_bounded_scores(self):
        layers = build_urban_growth_layers(sample_structures())

        for scenario, layer in layers.items():
            with self.subTest(scenario=scenario):
                self.assertFalse(layer.empty)
                for column in OUTPUT_COLUMNS:
                    self.assertIn(column, layer.columns)
                self.assertTrue(layer["suitability_score"].between(0, 1).all())
                self.assertEqual(
                    set(layer["source_authority"]), {"derived_proxy_from_structures"}
                )
                self.assertEqual(set(layer["scenario"]), {scenario})

    def test_empty_input_fails_clearly(self):
        empty = gpd.GeoDataFrame({"StructureID": []}, geometry=[], crs="EPSG:4326")

        with self.assertRaisesRegex(ValueError, "must not be empty"):
            build_urban_growth_layers(empty)

    def test_write_creates_one_geojson_per_scenario(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            structures_path = tmpdir_path / "structures.parquet"
            output_dir = tmpdir_path / "urban_growth"
            sample_structures().to_parquet(structures_path, index=False)

            paths = write_urban_growth_layers(structures_path, output_dir)

            self.assertEqual(set(paths), {scenario.slug for scenario in SCENARIOS})
            for path in paths.values():
                self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
