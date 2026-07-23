from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from structures_pipeline.exposure import (
    ExposureValidationError,
    assign_structures_to_wards,
    normalize_ward_frame,
)
from structures_pipeline.india_osm import (
    CHENNAI_CANONICAL_COLUMNS,
    build_chennai_osm_structures,
)


def _write_sources(tmp_path):
    wards = gpd.GeoDataFrame(
        [
            {"ward_id": "1", "ward_name": "Ward 1"},
            {"ward_id": "2", "ward_name": "Ward 2"},
        ],
        geometry=[box(80.0, 13.0, 80.1, 13.1), box(80.1, 13.0, 80.2, 13.1)],
        crs="EPSG:4326",
    )
    buildings = gpd.GeoDataFrame(
        [
            {"osm_id": 10, "building": "house", "name": "Known type"},
            {"osm_id": 11, "building": "yes", "name": None},
            {"osm_id": 12, "building": "house", "name": "duplicate"},
            {"osm_id": 13, "building": "warehouse", "name": "outside"},
        ],
        geometry=[
            box(80.01, 13.01, 80.02, 13.02),
            box(80.11, 13.01, 80.12, 13.02),
            box(80.01, 13.01, 80.02, 13.02),
            box(81.0, 14.0, 81.01, 14.01),
        ],
        crs="EPSG:4326",
    )
    ward_path = tmp_path / "wards.geojson"
    building_path = tmp_path / "buildings.geojson"
    manifest_path = tmp_path / "source_manifest.json"
    wards.to_file(ward_path, driver="GeoJSON")
    buildings.to_file(building_path, driver="GeoJSON")
    manifest_path.write_text(
        json.dumps(
            {
                "updated": "2026-07-04",
                "gcc_wards": {"status": "ready", "features": 2},
                "osm": {"status": "ready", "feature_counts": {"buildings": 4}},
            }
        )
    )
    return building_path, ward_path, manifest_path


def test_chennai_osm_builder_is_source_only_and_reconciles_counts(tmp_path):
    building_path, ward_path, manifest_path = _write_sources(tmp_path)

    canonical, wards, report = build_chennai_osm_structures(
        buildings_path=building_path,
        wards_path=ward_path,
        manifest_path=manifest_path,
        data_refresh_timestamp="2026-07-23T12:00:00+00:00",
    )

    assert list(canonical.columns) == CHENNAI_CANONICAL_COLUMNS
    assert canonical["StructureID"].tolist() == ["osm_building_10", "osm_building_11"]
    assert canonical["StructureType"].tolist()[0] == "residential"
    assert pd.isna(canonical["StructureType"].tolist()[1])
    assert canonical["NumStories"].isna().all()
    assert canonical["NumUnits"].isna().all()
    assert canonical["OccupantCount"].isna().all()
    assert canonical["SourceAuthority"].eq("OpenStreetMap contributors").all()
    assert report["source_counts"] == {
        "raw_candidate_count": 4,
        "exact_duplicate_quarantine_count": 1,
        "outside_gcc_aoi_count": 1,
        "canonical_count": 2,
        "reconciled": True,
    }
    assert len(wards) == 2


def test_ward_overlap_requires_explicit_source_defect_policy():
    wards = gpd.GeoDataFrame(
        [{"ward_id": "1"}, {"ward_id": "2"}],
        geometry=[box(80, 13, 80.2, 13.2), box(80.1, 13, 80.3, 13.2)],
        crs="EPSG:4326",
    )

    with pytest.raises(ExposureValidationError, match="overlap"):
        normalize_ward_frame(wards, ward_id_column="ward_id")

    accepted = normalize_ward_frame(
        wards,
        ward_id_column="ward_id",
        allow_overlaps=True,
    )
    assert accepted.attrs["overlap_diagnostics"]["overlap_pair_count"] == 1


def test_ambiguous_ward_assignment_uses_only_unique_largest_overlap():
    wards = gpd.GeoDataFrame(
        [{"ward_id": "1"}, {"ward_id": "2"}],
        geometry=[box(80, 13, 80.2, 13.2), box(80.1, 13, 80.3, 13.2)],
        crs="EPSG:4326",
    )
    structures = gpd.GeoDataFrame(
        [{"StructureID": "s1"}],
        geometry=[box(80.08, 13.05, 80.16, 13.15)],
        crs="EPSG:4326",
    )

    assigned, report = assign_structures_to_wards(
        structures,
        wards,
        ward_id_column="ward_id",
        resolve_ambiguous_by_largest_overlap=True,
    )

    assert assigned.iloc[0]["ward_id"] == "1"
    assert assigned.iloc[0]["ward_assignment_method"] == "unique_largest_overlap"
    assert report["resolved_ambiguity_count"] == 1
    assert report["ambiguous_count"] == 0
