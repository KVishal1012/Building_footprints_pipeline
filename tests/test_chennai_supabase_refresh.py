from __future__ import annotations

import json
from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from scripts.run_chennai_supabase_refresh import (
    deterministic_source_run_id,
    run,
    validate_acceptance_inputs,
)
from structures_pipeline.india_osm import CHENNAI_CANONICAL_COLUMNS


def _canonical_snapshot():
    row = {column: pd.NA for column in CHENNAI_CANONICAL_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": "osm_building_10",
            "PlaceGEOID": "IN-TN-CHENNAI",
            "City": "Chennai",
            "State": "Tamil Nadu",
            "StateFP": "TN",
            "Country": "India",
            "created_at": "2026-07-23T12:00:00+00:00",
            "updated_at": "2026-07-23T12:00:00+00:00",
            "updated_by": "test",
            "change_log": "[]",
            "data_refresh_timestamp": "2026-07-23T12:00:00+00:00",
            "last_refreshed": "2026-07-23T12:00:00+00:00",
            "source_as_of": "2026-07-04",
            "CoverageTier": "Tier 4",
            "LoadSource": "openstreetmap",
            "RawDataSource": "openstreetmap",
            "FootprintSource": "openstreetmap",
            "StructureType": "residential",
            "StructureTypeRaw": "house",
            "StructureTypeSource": "openstreetmap",
            "FootprintArea_m2": 100.0,
            "FootprintArea_sqft": 1076.391,
            "SourceAuthority": "OpenStreetMap contributors",
            "SourceFamily": "open_community",
            "ProvenanceTier": "open_community",
        }
    )
    return gpd.GeoDataFrame(
        [row],
        geometry=[box(80.1234567890123, 13.1, 80.1244567890123, 13.101)],
        crs="EPSG:4326",
    )[CHENNAI_CANONICAL_COLUMNS]


def _settings(tmp_path):
    source = tmp_path / "buildings.geojson"
    source.write_bytes(b"stable acquired OSM snapshot")
    canonical_path = tmp_path / "structures.parquet"
    report_path = tmp_path / "acceptance.json"
    _canonical_snapshot().to_parquet(canonical_path, index=False)
    report_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "source_as_of": "2026-07-04",
                "data_refresh_timestamp": "2026-07-23T12:00:00+00:00",
                "source_counts": {"canonical_count": 1},
                "quality": {"release_gates": {"status": "passed"}},
            }
        )
    )
    return SimpleNamespace(
        CANONICAL_OUTPUT_PATH=canonical_path,
        ACCEPTANCE_REPORT_PATH=report_path,
        OSM_BUILDINGS_PATH=source,
        LIFECYCLE_REPORT_PATH=tmp_path / "lifecycle.json",
        DRY_RUN=True,
        SUPABASE_STORE="in_memory",
        PROMOTE_TO_CANONICAL=True,
        SUPABASE_URL=None,
        SUPABASE_SERVICE_ROLE_ENV="SUPABASE_SERVICE_ROLE_KEY",
    )


def test_chennai_lifecycle_dry_run_passes_without_database_mutation(tmp_path):
    settings = _settings(tmp_path)

    result = run(settings)

    assert result["status"] == "passed"
    assert result["dry_run"] is True
    assert result["input_rows"] == 1
    assert result["change_counts"] == {"insert": 1}
    assert result["promoted_count"] == 1
    assert result["failed_count"] == 0
    assert result["release_gate_status"] == "passed"
    assert json.loads(settings.LIFECYCLE_REPORT_PATH.read_text())["status"] == "passed"


def test_chennai_run_id_is_stable_for_same_acquired_snapshot(tmp_path):
    settings = _settings(tmp_path)

    first = deterministic_source_run_id("2026-07-04", settings.OSM_BUILDINGS_PATH)
    second = deterministic_source_run_id("2026-07-04", settings.OSM_BUILDINGS_PATH)

    assert first == second
    assert first.startswith("openstreetmap_chennai_tamil_nadu_2026_07_04_")


def test_acceptance_snapshot_requires_exact_approved_columns(tmp_path):
    settings = _settings(tmp_path)
    altered = _canonical_snapshot()
    altered["unexpected"] = "not approved"
    altered.to_parquet(settings.CANONICAL_OUTPUT_PATH, index=False)

    with pytest.raises(ValueError, match="approved Chennai contract"):
        validate_acceptance_inputs(
            settings.CANONICAL_OUTPUT_PATH,
            settings.ACCEPTANCE_REPORT_PATH,
        )
