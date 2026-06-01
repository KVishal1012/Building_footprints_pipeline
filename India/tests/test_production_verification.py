import json
import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from production_verification import (  # noqa: E402
    AuthoritativeSourceRule,
    CityVerificationRule,
    VerificationConfig,
    calibrate_thresholds,
    verify_outputs,
)


class ProductionVerificationTests(unittest.TestCase):
    def _write_outputs(
        self,
        tmp: Path,
        structures: gpd.GeoDataFrame,
        layers: gpd.GeoDataFrame,
        links: pd.DataFrame,
    ) -> VerificationConfig:
        """Write one complete verification fixture and return its config."""
        structures_path = tmp / "structures.parquet"
        layers_path = tmp / "processing_layers.parquet"
        links_path = tmp / "structure_processing_links.parquet"
        metrics_path = tmp / "processing_metrics.json"
        structures.to_parquet(structures_path, index=False)
        layers.to_parquet(layers_path, index=False)
        links.to_parquet(links_path, index=False)
        metrics_path.write_text(json.dumps({"total_layer_rows": len(layers), "total_links": len(links)}))
        for path in (structures_path, layers_path, links_path):
            self._write_sidecar(path)
        return VerificationConfig(
            structure_path=structures_path,
            layers_path=layers_path,
            links_path=links_path,
            metrics_path=metrics_path,
        )

    def _write_sidecar(self, path: Path) -> None:
        Path(f"{path}.metadata.json").write_text(json.dumps({"dataset": path.name}))

    def _base_layers(self) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(
            {
                "LayerID": ["l1", "l2"],
                "LayerType": ["planning_context", "segmentation"],
                "City": ["Chennai", "Bengaluru"],
                "State": ["Tamil Nadu", "Karnataka"],
                "Country": ["India", "India"],
                "SourceName": ["water_context", "segformer"],
                "SourceAuthority": ["NRSC/ISRO", "local_model_run"],
                "SourceFamily": ["nrsc_isro", "model_export"],
                "ProvenanceTier": ["authoritative", "model"],
                "PredictionKind": ["authoritative_context", "model_prediction"],
                "SourcePath": ["a.geojson", "b.geojson"],
                "ModelFamily": [None, "SegFormer"],
                "ModelName": [None, "segformer-v1"],
                "ModelVersion": [None, "v1"],
                "Task": ["blue_green_network_protection", "semantic_segmentation"],
                "RunID": ["run", "run"],
                "RunTimestamp": ["2026-05-02T00:00:00+00:00"] * 2,
                "Label": ["canal", "built_up"],
                "Score": [None, 0.93],
                "Value": ["Buckingham Canal", None],
                "DateFrom": [None, None],
                "DateTo": [None, None],
                "Scenario": [
                    "chennai_tamil_nadu_india_blue_green_network_protection_realworld_v1",
                    "bengaluru_karnataka_india_floodplain_lock_in_realworld_v1",
                ],
                "HorizonHours": [None, None],
                "DepthM": [None, None],
                "Probability": [None, None],
            },
            geometry=[Point(80.2, 13.0), Point(77.59, 12.97)],
            crs="EPSG:4326",
        )

    def test_verify_outputs_passes_for_healthy_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            structures_path = tmp / "structures.parquet"
            layers_path = tmp / "processing_layers.parquet"
            links_path = tmp / "structure_processing_links.parquet"
            metrics_path = tmp / "processing_metrics.json"

            structures = gpd.GeoDataFrame(
                {
                    "StructureID": ["s1", "s2"],
                    "City": ["Chennai", "Bengaluru"],
                },
                geometry=[box(80.19, 12.99, 80.21, 13.01), box(77.58, 12.96, 77.60, 12.98)],
                crs="EPSG:4326",
            )
            layers = self._base_layers()
            links = pd.DataFrame(
                {
                    "StructureID": ["s1", "s2"],
                    "City": ["Chennai", "Bengaluru"],
                    "Scenario": layers["Scenario"],
                }
            )
            metrics = {
                "total_layer_rows": 2,
                "total_links": 2,
                "link_rate": 1.0,
                "rows_by_prediction_kind": {
                    "authoritative_context": 1,
                    "model_prediction": 1,
                },
            }

            structures.to_parquet(structures_path, index=False)
            layers.to_parquet(layers_path, index=False)
            links.to_parquet(links_path, index=False)
            metrics_path.write_text(json.dumps(metrics))
            for path in (structures_path, layers_path, links_path):
                self._write_sidecar(path)

            config = VerificationConfig(
                structure_path=structures_path,
                layers_path=layers_path,
                links_path=links_path,
                metrics_path=metrics_path,
                cities={
                    "Chennai": CityVerificationRule(
                        min_link_rate=1.0,
                        required_scenarios=[
                            "chennai_tamil_nadu_india_blue_green_network_protection_realworld_v1"
                        ],
                        min_authoritative_rows=1,
                        min_model_rows=0,
                    ),
                    "Bengaluru": CityVerificationRule(
                        min_link_rate=1.0,
                        required_scenarios=[
                            "bengaluru_karnataka_india_floodplain_lock_in_realworld_v1"
                        ],
                        min_authoritative_rows=0,
                        min_model_rows=1,
                    ),
                },
            )
            report = verify_outputs(config)

        self.assertTrue(report["passed"])
        self.assertEqual(len(report["errors"]), 0)

    def test_verify_outputs_fails_for_missing_scenario_and_low_link_rate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            structures_path = tmp / "structures.parquet"
            layers_path = tmp / "processing_layers.parquet"
            links_path = tmp / "structure_processing_links.parquet"
            metrics_path = tmp / "processing_metrics.json"

            structures = gpd.GeoDataFrame(
                {
                    "StructureID": ["s1", "s2"],
                    "City": ["Chennai", "Chennai"],
                },
                geometry=[box(80.19, 12.99, 80.21, 13.01), box(80.22, 13.02, 80.23, 13.03)],
                crs="EPSG:4326",
            )
            layers = self._base_layers().iloc[[0]].copy()
            links = pd.DataFrame({"StructureID": ["s1"], "City": ["Chennai"], "Scenario": layers["Scenario"]})
            metrics = {"total_layer_rows": 1, "total_links": 1, "link_rate": 0.5}

            structures.to_parquet(structures_path, index=False)
            layers.to_parquet(layers_path, index=False)
            links.to_parquet(links_path, index=False)
            metrics_path.write_text(json.dumps(metrics))
            for path in (structures_path, layers_path, links_path):
                self._write_sidecar(path)

            config = VerificationConfig(
                structure_path=structures_path,
                layers_path=layers_path,
                links_path=links_path,
                metrics_path=metrics_path,
                cities={
                    "Chennai": CityVerificationRule(
                        min_link_rate=0.8,
                        required_scenarios=[
                            "chennai_tamil_nadu_india_blue_green_network_protection_realworld_v1",
                            "chennai_tamil_nadu_india_floodplain_lock_in_realworld_v1",
                        ],
                        min_authoritative_rows=2,
                        min_model_rows=1,
                    ),
                },
            )
            report = verify_outputs(config)

        self.assertFalse(report["passed"])
        self.assertTrue(any("below minimum" in error for error in report["errors"]))
        self.assertTrue(any("missing required scenarios" in error for error in report["errors"]))

    def test_verify_outputs_fails_for_incomplete_provenance_and_custom_family(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            structures = gpd.GeoDataFrame(
                {"StructureID": ["s1"], "City": ["Chennai"]},
                geometry=[box(80.19, 12.99, 80.21, 13.01)],
                crs="EPSG:4326",
            )
            layers = self._base_layers().iloc[[0]].copy()
            layers["SourceAuthority"] = ""
            layers["SourceFamily"] = "custom"
            links = pd.DataFrame({"StructureID": ["s1"], "City": ["Chennai"]})
            config = self._write_outputs(tmp, structures, layers, links)
            report = verify_outputs(config)

        self.assertFalse(report["passed"])
        self.assertTrue(any("blank SourceAuthority" in error for error in report["errors"]))
        self.assertTrue(any("strict-mode SourceFamily" in error for error in report["errors"]))

    def test_verify_outputs_fails_for_required_authoritative_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            structures = gpd.GeoDataFrame(
                {"StructureID": ["s1"], "City": ["Chennai"]},
                geometry=[box(80.19, 12.99, 80.21, 13.01)],
                crs="EPSG:4326",
            )
            layers = self._base_layers().iloc[[0]].copy()
            links = pd.DataFrame({"StructureID": ["s1"], "City": ["Chennai"]})
            config = self._write_outputs(tmp, structures, layers, links)
            config.cities = {
                "Chennai": CityVerificationRule(
                    authoritative_sources=[
                        AuthoritativeSourceRule(
                            source_name="missing_municipal_layer",
                            min_rows=1,
                        )
                    ]
                )
            }
            report = verify_outputs(config)

        self.assertFalse(report["passed"])
        self.assertTrue(any("missing_municipal_layer" in error for error in report["errors"]))

    def test_calibrate_thresholds_uses_ninety_percent_floor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            structures = gpd.GeoDataFrame(
                {"StructureID": ["s1", "s2"], "City": ["Chennai", "Chennai"]},
                geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)],
                crs="EPSG:4326",
            )
            layers = self._base_layers().iloc[[0]].copy()
            links = pd.DataFrame({"StructureID": ["s1"], "City": ["Chennai"]})
            config = self._write_outputs(tmp, structures, layers, links)
            config.cities = {
                "Chennai": CityVerificationRule(),
                "Bengaluru": CityVerificationRule(),
            }
            report = calibrate_thresholds(config)

        self.assertEqual(report["cities"]["Chennai"]["measured_link_rate"], 0.5)
        self.assertEqual(report["cities"]["Chennai"]["recommended_min_link_rate"], 0.45)
        self.assertEqual(report["cities"]["Bengaluru"]["recommended_min_link_rate"], 0.0005)


if __name__ == "__main__":
    unittest.main()
