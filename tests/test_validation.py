import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS
from structures_pipeline.validation import validate_output, validate_release_gates


def test_validate_output_accepts_required_schema():
    row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": "s1",
            "FootprintArea_m2": 10.0,
            "LoadSource": "overture",
            "RawDataSource": "overture",
            "FootprintSource": "overture",
            "CoverageTier": "Tier 4",
            "OccupantCountSource": "acs",
            "OccupantCount": 3,
            "created_at": "2026-06-04T00:00:00+00:00",
            "updated_at": "2026-06-04T00:00:00+00:00",
            "updated_by": "unit_test",
            "change_log": "[]",
            "data_refresh_timestamp": "2026-06-04T00:00:00+00:00",
            "last_refreshed": "2026-06-04T00:00:00+00:00",
            "source_as_of": "2026-06",
        }
    )
    gdf = gpd.GeoDataFrame([row], geometry=[box(0, 0, 0.001, 0.001)], crs="EPSG:4326")

    metrics = validate_output(gdf)

    assert metrics["row_count"] == 1
    assert metrics["acs_fallback_count"] == 1
    assert metrics["release_gates"]["status"] == "passed"


def test_validate_release_gates_reports_manifest_and_source_of_truth_contract():
    row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": "s1",
            "FootprintArea_m2": 10.0,
            "LoadSource": "nyc_pluto",
            "RawDataSource": "nyc_pluto",
            "FootprintSource": "nyc_pluto",
            "CoverageTier": "Tier 1",
            "StructureType": "residential",
            "StructureTypeSource": "nyc_pluto_land_use",
            "NumStories": 10,
            "NumStoriesSource": "nyc_pluto_num_floors",
            "created_at": "2026-06-04T00:00:00+00:00",
            "updated_at": "2026-06-04T00:00:00+00:00",
            "updated_by": "unit_test",
            "change_log": "[]",
            "data_refresh_timestamp": "2026-06-04T00:00:00+00:00",
            "last_refreshed": "2026-06-04T00:00:00+00:00",
            "source_as_of": "2026-06",
        }
    )
    gdf = gpd.GeoDataFrame([row], geometry=[box(0, 0, 0.001, 0.001)], crs="EPSG:4326")
    manifest = {
        "release_id": "release-test",
        "generated_at": "2026-06-04T00:00:00+00:00",
        "quality_contract": {"source_of_truth": "public.structures"},
        "freshness": {"data_refresh_timestamp": "2026-06-04T00:00:00+00:00"},
        "coverage": {},
        "delivery": {},
    }

    gates = validate_release_gates(gdf, manifest=manifest)

    assert gates["status"] == "passed"
    assert gates["checks"]["release_manifest_complete"]["passed"] is True


def test_validate_output_rejects_ai_as_raw_source():
    row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": "s1",
            "FootprintArea_m2": 10.0,
            "LoadSource": "sql_server",
            "RawDataSource": "ml_inference",
            "FootprintSource": "overture",
            "CoverageTier": "Tier 4",
            "created_at": "2026-06-04T00:00:00+00:00",
            "updated_at": "2026-06-04T00:00:00+00:00",
            "updated_by": "unit_test",
            "change_log": "[]",
            "data_refresh_timestamp": "2026-06-04T00:00:00+00:00",
            "last_refreshed": "2026-06-04T00:00:00+00:00",
            "source_as_of": "2026-06",
        }
    )
    gdf = gpd.GeoDataFrame([row], geometry=[box(0, 0, 0.001, 0.001)], crs="EPSG:4326")

    try:
        validate_output(gdf)
    except ValueError as exc:
        assert "RawDataSource" in str(exc)
    else:
        raise AssertionError("Expected RawDataSource validation failure")


def test_validate_output_rejects_missing_attribute_datasource():
    row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": "s1",
            "FootprintArea_m2": 10.0,
            "LoadSource": "overture",
            "RawDataSource": "overture",
            "FootprintSource": "overture",
            "CoverageTier": "Tier 4",
            "StructureType": "residential",
            "created_at": "2026-06-04T00:00:00+00:00",
            "updated_at": "2026-06-04T00:00:00+00:00",
            "updated_by": "unit_test",
            "change_log": "[]",
            "data_refresh_timestamp": "2026-06-04T00:00:00+00:00",
            "last_refreshed": "2026-06-04T00:00:00+00:00",
            "source_as_of": "2026-06",
        }
    )
    gdf = gpd.GeoDataFrame([row], geometry=[box(0, 0, 0.001, 0.001)], crs="EPSG:4326")

    try:
        validate_output(gdf)
    except ValueError as exc:
        assert "StructureTypeSource" in str(exc)
    else:
        raise AssertionError("Expected missing attribute datasource validation failure")


def test_validate_output_rejects_ai_as_attribute_source():
    row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": "s1",
            "FootprintArea_m2": 10.0,
            "LoadSource": "overture",
            "RawDataSource": "overture",
            "FootprintSource": "overture",
            "CoverageTier": "Tier 4",
            "StructureType": "residential",
            "StructureTypeSource": "ml_inference",
            "created_at": "2026-06-04T00:00:00+00:00",
            "updated_at": "2026-06-04T00:00:00+00:00",
            "updated_by": "unit_test",
            "change_log": "[]",
            "data_refresh_timestamp": "2026-06-04T00:00:00+00:00",
            "last_refreshed": "2026-06-04T00:00:00+00:00",
            "source_as_of": "2026-06",
        }
    )
    gdf = gpd.GeoDataFrame([row], geometry=[box(0, 0, 0.001, 0.001)], crs="EPSG:4326")

    try:
        validate_output(gdf)
    except ValueError as exc:
        assert "StructureTypeSource" in str(exc)
    else:
        raise AssertionError("Expected AI attribute source validation failure")


def test_validate_output_rejects_prediction_without_metadata():
    row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": "s1",
            "FootprintArea_m2": 10.0,
            "LoadSource": "overture",
            "RawDataSource": "overture",
            "FootprintSource": "overture",
            "CoverageTier": "Tier 4",
            "PredictedNumStories": 3,
            "created_at": "2026-06-04T00:00:00+00:00",
            "updated_at": "2026-06-04T00:00:00+00:00",
            "updated_by": "unit_test",
            "change_log": "[]",
            "data_refresh_timestamp": "2026-06-04T00:00:00+00:00",
            "last_refreshed": "2026-06-04T00:00:00+00:00",
            "source_as_of": "2026-06",
        }
    )
    gdf = gpd.GeoDataFrame([row], geometry=[box(0, 0, 0.001, 0.001)], crs="EPSG:4326")

    try:
        validate_output(gdf)
    except ValueError as exc:
        assert "PredictionKind" in str(exc)
    else:
        raise AssertionError("Expected missing prediction metadata validation failure")
