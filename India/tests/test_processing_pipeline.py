import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing_pipeline import (  # noqa: E402
    PROCESSING_LAYER_COLUMNS,
    PROCESSING_LINK_COLUMNS,
    ProcessingConfig,
    build_processing_metrics,
    link_processing_layers_to_structures,
    read_processing_source,
    run_processing_pipeline,
    standardize_processing_layer,
)


class ProcessingPipelineTests(unittest.TestCase):
    def test_standardize_processing_layer_uses_separate_schema(self):
        raw = gpd.GeoDataFrame(
            {"class": ["built_up"], "confidence": [0.91]},
            geometry=[box(80.20, 13.00, 80.201, 13.001)],
            crs="EPSG:4326",
        )
        source = {
            "layer_type": "segmentation",
            "city": "Chennai",
            "state": "TN",
            "source_name": "segformer_chennai_test",
            "model_family": "SegFormer",
            "model_name": "example/segformer",
            "field_map": {"Label": "class", "Score": "confidence"},
        }

        out = standardize_processing_layer(raw, source, ProcessingConfig())

        self.assertEqual(list(out.columns), PROCESSING_LAYER_COLUMNS)
        self.assertEqual(out.loc[0, "LayerType"], "segmentation")
        self.assertEqual(out.loc[0, "State"], "Tamil Nadu")
        self.assertEqual(out.loc[0, "Label"], "built_up")
        self.assertAlmostEqual(out.loc[0, "Score"], 0.91)

    def test_polygon_processing_layer_links_to_structures(self):
        structures = gpd.GeoDataFrame(
            {"StructureID": ["s1"]},
            geometry=[box(80.20, 13.00, 80.201, 13.001)],
            crs="EPSG:4326",
        )
        raw = gpd.GeoDataFrame(
            {"risk": ["high"], "probability": [0.72]},
            geometry=[box(80.2002, 13.0002, 80.2012, 13.0012)],
            crs="EPSG:4326",
        )
        source = {
            "layer_type": "flood_prediction",
            "city": "Chennai",
            "state": "Tamil Nadu",
            "source_name": "flood_test",
            "model_family": "ConvLSTM",
            "field_map": {"Label": "risk", "Probability": "probability"},
        }
        layers = standardize_processing_layer(raw, source, ProcessingConfig())

        links = link_processing_layers_to_structures(
            structures, layers, ProcessingConfig(min_intersection_area_m2=0)
        )

        self.assertEqual(list(links.columns), PROCESSING_LINK_COLUMNS)
        self.assertEqual(links.loc[0, "StructureID"], "s1")
        self.assertEqual(links.loc[0, "LayerType"], "flood_prediction")
        self.assertEqual(links.loc[0, "MatchMethod"], "area_intersection")
        self.assertGreater(links.loc[0, "MatchArea_m2"], 0)
        self.assertGreater(links.loc[0, "StructureCoverage"], 0)

    def test_point_processing_layer_links_to_structures(self):
        structures = gpd.GeoDataFrame(
            {"StructureID": ["s1"]},
            geometry=[box(80.20, 13.00, 80.201, 13.001)],
            crs="EPSG:4326",
        )
        raw = gpd.GeoDataFrame(
            {"planning_label": ["redevelopment_priority"]},
            geometry=[Point(80.2005, 13.0005)],
            crs="EPSG:4326",
        )
        source = {
            "layer_type": "urban_planning",
            "city": "Chennai",
            "state": "Tamil Nadu",
            "source_name": "planning_test",
            "field_map": {"Label": "planning_label"},
        }
        layers = standardize_processing_layer(raw, source, ProcessingConfig())

        links = link_processing_layers_to_structures(structures, layers, ProcessingConfig())

        self.assertEqual(links.loc[0, "StructureID"], "s1")
        self.assertEqual(links.loc[0, "MatchMethod"], "point_within_structure")
        self.assertEqual(links.loc[0, "Label"], "redevelopment_priority")

    def test_mixed_processing_layers_link_points_and_polygons(self):
        structures = gpd.GeoDataFrame(
            {"StructureID": ["s1"]},
            geometry=[box(80.20, 13.00, 80.201, 13.001)],
            crs="EPSG:4326",
        )
        polygon_raw = gpd.GeoDataFrame(
            {"class": ["built_up"]},
            geometry=[box(80.20, 13.00, 80.201, 13.001)],
            crs="EPSG:4326",
        )
        point_raw = gpd.GeoDataFrame(
            {"planning_label": ["redevelopment_priority"]},
            geometry=[Point(80.2005, 13.0005)],
            crs="EPSG:4326",
        )
        polygon_layer = standardize_processing_layer(
            polygon_raw,
            {
                "layer_type": "segmentation",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "source_name": "polygon_test",
                "field_map": {"Label": "class"},
            },
            ProcessingConfig(),
        )
        point_layer = standardize_processing_layer(
            point_raw,
            {
                "layer_type": "urban_planning",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "source_name": "point_test",
                "field_map": {"Label": "planning_label"},
            },
            ProcessingConfig(),
        )
        layers = gpd.GeoDataFrame(
            pd.concat([polygon_layer, point_layer], ignore_index=True),
            geometry="geometry",
            crs="EPSG:4326",
        )

        links = link_processing_layers_to_structures(
            structures, layers, ProcessingConfig(min_intersection_area_m2=0)
        )

        self.assertEqual(len(links), 2)
        self.assertEqual(
            set(links["MatchMethod"]),
            {"area_intersection", "point_within_structure"},
        )

    def test_missing_required_field_map_column_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_path = tmpdir_path / "source.geojson"
            raw = gpd.GeoDataFrame(
                {"label_only": ["x"]},
                geometry=[Point(80.2, 13.0)],
                crs="EPSG:4326",
            )
            raw.to_file(source_path, driver="GeoJSON")

            config = ProcessingConfig(enforce_field_map_columns=True)
            source = {
                "path": str(source_path),
                "field_map": {"Label": "missing_label_column"},
            }
            with self.assertRaises(ValueError):
                read_processing_source(source, config)

    def test_missing_crs_fails_when_enforced(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_path = tmpdir_path / "source.parquet"
            raw = gpd.GeoDataFrame(
                {"label": ["x"]},
                geometry=[Point(80.2, 13.0)],
                crs=None,
            )
            raw.to_parquet(source_path, index=False)

            config = ProcessingConfig(enforce_crs=True)
            source = {"path": str(source_path)}
            with self.assertRaises(ValueError):
                read_processing_source(source, config)

    def test_geometry_cleanup_to_empty_fails_when_enforced(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_path = tmpdir_path / "source.geojson"
            raw = gpd.GeoDataFrame(
                {"label": ["x"]},
                geometry=[None],
                crs="EPSG:4326",
            )
            raw.to_file(source_path, driver="GeoJSON")

            config = ProcessingConfig(enforce_geometry_non_empty=True)
            source = {"path": str(source_path)}
            with self.assertRaises(ValueError):
                read_processing_source(source, config)

    def test_null_scenario_rate_gate_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            structures_path = tmpdir_path / "structures.parquet"
            source_path = tmpdir_path / "source.geojson"
            output_dir = tmpdir_path / "out"
            raw_dir = tmpdir_path / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)

            structures = gpd.GeoDataFrame(
                {"StructureID": ["s1"]},
                geometry=[box(80.20, 13.00, 80.201, 13.001)],
                crs="EPSG:4326",
            )
            structures.to_parquet(structures_path, index=False)
            raw = gpd.GeoDataFrame(
                {"planning_label": ["a"]},
                geometry=[Point(80.2005, 13.0005)],
                crs="EPSG:4326",
            )
            raw.to_file(source_path, driver="GeoJSON")

            config = ProcessingConfig(
                data_dir=tmpdir_path,
                structure_path=structures_path,
                output_dir=output_dir,
                raw_dir=raw_dir,
                max_null_scenario_rate=0.05,
            )
            sources = [
                {
                    "layer_type": "urban_planning",
                    "city": "Chennai",
                    "state": "Tamil Nadu",
                    "source_name": "scenario_missing",
                    "path": str(source_path),
                    "field_map": {"Label": "planning_label"},
                }
            ]
            with self.assertRaises(ValueError):
                run_processing_pipeline(sources, config)

    def test_build_processing_metrics_includes_link_rate(self):
        structures = gpd.GeoDataFrame(
            {"StructureID": ["s1", "s2"]},
            geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)],
            crs="EPSG:4326",
        )
        layers = gpd.GeoDataFrame(
            {
                "LayerID": ["l1"],
                "LayerType": ["urban_planning"],
                "SourceName": ["src"],
                "Scenario": ["test_scenario"],
                "geometry": [Point(0.5, 0.5)],
            },
            geometry="geometry",
            crs="EPSG:4326",
        )
        links = pd.DataFrame(
            {
                "StructureID": ["s1"],
                "LayerID": ["l1"],
                "LayerType": ["urban_planning"],
                "SourceName": ["src"],
                "Scenario": ["test_scenario"],
            }
        )

        metrics = build_processing_metrics(layers, links, structures)
        self.assertEqual(metrics["total_layer_rows"], 1)
        self.assertEqual(metrics["total_links"], 1)
        self.assertEqual(metrics["unique_linked_structures"], 1)
        self.assertAlmostEqual(metrics["link_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
