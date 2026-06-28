from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS
from structures_pipeline.exposure import (
    ExposureValidationError,
    build_ward_structure_exposure,
    write_ward_structure_exposure,
)


def _structure_row(
    structure_id: str,
    *,
    structure_type="residential",
    units=4,
    stories=2,
    occupants=12,
    source="overture_maps",
):
    row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": structure_id,
            "PlaceGEOID": "IN-TN-CHENNAI",
            "City": "Chennai",
            "State": "Tamil Nadu",
            "StateFP": "TN",
            "Country": "India",
            "created_at": "2026-06-23T12:00:00+00:00",
            "updated_at": "2026-06-23T12:00:00+00:00",
            "updated_by": "test",
            "change_log": "[]",
            "data_refresh_timestamp": "2026-06-23T12:00:00+00:00",
            "last_refreshed": "2026-06-23T12:00:00+00:00",
            "source_as_of": "2026-Q2",
            "CoverageTier": "Tier 4",
            "LoadSource": source,
            "RawDataSource": source,
            "FootprintSource": source,
            "StructureType": structure_type,
            "NumUnits": units,
            "NumStories": stories,
            "FootprintArea_m2": 100.0,
            "FootprintArea_sqft": 1076.39,
            "OccupantCount": occupants,
            "StructureTypeSource": source,
            "StructureTypeConfidence": 0.70,
            "NumUnitsSource": source if pd.notna(units) else pd.NA,
            "NumUnitsConfidence": 0.50 if pd.notna(units) else pd.NA,
            "NumStoriesSource": source if pd.notna(stories) else pd.NA,
            "NumStoriesConfidence": 0.50 if pd.notna(stories) else pd.NA,
            "OccupantCountSource": source if pd.notna(occupants) else pd.NA,
            "OccupantCountMethod": "source" if pd.notna(occupants) else pd.NA,
            "OccupantCountConfidence": 0.50 if pd.notna(occupants) else pd.NA,
            "PredictionKind": pd.NA,
            "AIDisclosureLevel": pd.NA,
        }
    )
    return row


def _structures(*items):
    rows = []
    geometries = []
    for row, geometry in items:
        rows.append(row)
        geometries.append(geometry)
    frame = gpd.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")
    frame["geometry_wkt"] = frame.geometry.to_wkt()
    return frame


def _wards():
    return gpd.GeoDataFrame(
        [{"ward_no": "1"}, {"ward_no": "2"}],
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
        crs="EPSG:4326",
    )


def test_build_ward_structure_exposure_aggregates_known_values_only(tmp_path):
    structures = _structures(
        (_structure_row("s1", structure_type="residential", units=4, stories=2, occupants=12), box(0.1, 0.1, 0.2, 0.2)),
        (_structure_row("s2", structure_type="public", units=1, stories=3, occupants=pd.NA), box(1.1, 0.1, 1.2, 0.2)),
    )

    payload = build_ward_structure_exposure(structures, _wards(), expected_ward_count=2)

    assert payload["metadata"]["release_gate_status"] == "passed"
    assert payload["metadata"]["assignment"]["assigned_count"] == 2
    ward_1 = next(row for row in payload["wards"] if row["ward_no"] == "1")
    ward_2 = next(row for row in payload["wards"] if row["ward_no"] == "2")
    assert ward_1["structure_count"] == 1
    assert ward_1["known_occupant_count_total"] == 12.0
    assert ward_2["public_structure_count"] == 1
    assert ward_2["known_occupant_count_total"] is None
    assert ward_2["attribute_completeness"]["occupant_count"] == 0.0

    path = tmp_path / "structure_exposure.json"
    write_ward_structure_exposure(payload, path)
    assert json.loads(path.read_text())["metadata"]["feature_type"] == "structure_exposure"


def test_structure_exposure_strict_mode_blocks_unassigned_structures():
    structures = _structures(
        (_structure_row("s1"), box(10, 10, 10.1, 10.1)),
    )

    with pytest.raises(ExposureValidationError, match="unassigned_structure_ward_assignment"):
        build_ward_structure_exposure(structures, _wards())


def test_structure_exposure_can_report_unassigned_when_explicitly_allowed():
    structures = _structures(
        (_structure_row("s1"), box(10, 10, 10.1, 10.1)),
    )

    payload = build_ward_structure_exposure(structures, _wards(), strict=False)

    assert payload["metadata"]["release_gate_status"] == "failed"
    assert payload["metadata"]["assignment"]["unassigned_count"] == 1
    assert payload["wards"][0]["structure_count"] == 0


def test_structure_exposure_reuses_canonical_datasource_gates():
    row = _structure_row("s1", structure_type="residential")
    row["StructureTypeSource"] = pd.NA
    structures = _structures((row, box(0.1, 0.1, 0.2, 0.2)))

    with pytest.raises(ValueError, match="StructureTypeSource"):
        build_ward_structure_exposure(structures, _wards())
