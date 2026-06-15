import json

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from structures_pipeline.config import PipelineConfig
from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS
from structures_pipeline.release import build_release_manifest, write_release_manifest


def _frame():
    rows = []
    for structure_id, tier, prediction_kind, source in (
        ("s1", "Tier 1", pd.NA, "nyc_pluto"),
        ("s2", "Tier 3", "ml_inference", "overture"),
    ):
        has_prediction = str(prediction_kind) == "ml_inference"
        row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
        row.update(
            {
                "StructureID": structure_id,
                "PlaceGEOID": "3651000",
                "City": "Manhattan",
                "State": "New York",
                "StateFP": "36",
                "Country": "USA",
                "created_at": "2026-06-06T12:00:00+00:00",
                "updated_at": "2026-06-06T12:00:00+00:00",
                "updated_by": "unit_test",
                "change_log": "[]",
                "data_refresh_timestamp": "2026-06-06T12:00:00+00:00",
                "last_refreshed": "2026-06-06T12:00:00+00:00",
                "source_as_of": "2026-Q2",
                "CoverageTier": tier,
                "LoadSource": source,
                "RawDataSource": source,
                "FootprintSource": source,
                "StructureType": "residential",
                "StructureTypeRaw": "residential",
                "StructureTypeSource": f"{source}_land_use",
                "StructureTypeConfidence": 0.95,
                "NumUnits": 2,
                "NumUnitsSource": f"{source}_units",
                "NumUnitsConfidence": 0.95,
                "NumStories": 4,
                "NumStoriesSource": f"{source}_stories",
                "NumStoriesConfidence": 0.95,
                "FootprintArea_m2": 100.0,
                "FootprintArea_sqft": 1076.39,
                "OccupantCount": 5,
                "OccupantCountSource": "nsi",
                "OccupantCountMethod": "source",
                "OccupantCountConfidence": 0.95,
                "PredictionKind": prediction_kind,
                "PredictionModelName": "us_structure_ai" if has_prediction else pd.NA,
                "PredictionModelVersion": "v1" if has_prediction else pd.NA,
                "PredictionConfidence": 0.81 if has_prediction else pd.NA,
                "PredictionFeaturesUsed": "[\"FootprintArea_m2\"]" if has_prediction else pd.NA,
                "AIDisclosureLevel": "mandatory_ai_disclosure" if has_prediction else pd.NA,
            }
        )
        rows.append(row)
    return gpd.GeoDataFrame(
        rows,
        geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)],
        crs="EPSG:4326",
    )


def test_build_release_manifest_records_delivery_quality_and_coverage():
    config = PipelineConfig(
        release_id="release-test",
        data_refresh_timestamp="2026-06-06T12:00:00+00:00",
        delivery_formats=["csv", "geojson"],
        domain_extensions=["flood"],
        use_ai_predictions=True,
        refresh_metadata={"last_refreshed": "2026-06-04", "source_as_of": "2026-Q2"},
    )

    manifest = build_release_manifest(
        _frame(),
        config,
        delivery_paths={"csv": "/tmp/structures.csv"},
        coverage_paths={"gap_registry": "/tmp/gap_registry.csv"},
        extension_paths={"flood": "/tmp/flood.csv"},
        metrics=[{"City": "New York", "row_count": 2}],
    )

    assert manifest["release_id"] == "release-test"
    assert manifest["row_count"] == 2
    assert manifest["quality_contract"]["ai_policy"] == "suggest_only_never_overwrite"
    assert manifest["quality_contract"]["source_of_truth"] == "public.structures"
    assert manifest["quality_contract"]["canonical_database"]["platform"] == "supabase_postgres"
    assert manifest["quality_contract"]["release_gates"]["status"] == "passed"
    assert manifest["coverage"]["tier_counts"]["Tier 1"] == 1
    assert manifest["coverage"]["source_completeness"][0]["row_count"] == 1
    assert manifest["coverage"]["gap_registry"][0]["City"] == "Manhattan"
    assert manifest["ai"]["prediction_kind_counts"]["ml_inference"] == 1
    assert manifest["delivery"]["formats"] == ["csv", "geojson"]
    assert manifest["extensions"]["enabled"] == ["flood"]
    assert manifest["freshness"]["data_refresh_timestamp"] == "2026-06-06T12:00:00+00:00"


def test_write_release_manifest_outputs_json(tmp_path):
    config = PipelineConfig(
        release_id="release-test",
        release_output_dir=tmp_path / "release",
        write_release_metadata=True,
    )

    path = write_release_manifest(_frame(), config)

    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["release_id"] == "release-test"
    assert payload["product"] == "Structure Intelligence Database"
    assert payload["quality_contract"]["release_gates"]["status"] == "passed"
    assert payload["freshness"]["data_refresh_timestamp"] == "2026-06-06T12:00:00+00:00"
