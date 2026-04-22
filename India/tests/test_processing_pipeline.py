import sys
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, box


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing_pipeline import (  # noqa: E402
    PROCESSING_LAYER_COLUMNS,
    PROCESSING_LINK_COLUMNS,
    ProcessingConfig,
    link_processing_layers_to_structures,
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


if __name__ == "__main__":
    unittest.main()
