import json

import geopandas as gpd
from shapely.geometry import box

from structures_pipeline.config import PipelineConfig
from structures_pipeline.release import build_release_manifest, write_release_manifest


def _frame():
    return gpd.GeoDataFrame(
        {
            "StructureID": ["s1", "s2"],
            "CoverageTier": ["Tier 1", "Tier 3"],
            "PredictionKind": ["none", "ml_inference"],
        },
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
    assert manifest["coverage"]["tier_counts"]["Tier 1"] == 1
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
