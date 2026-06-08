import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from structures_pipeline.config import PipelineConfig
from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS
from structures_pipeline.refresh import (
    InMemoryRefreshStore,
    build_raw_structure_rows,
    build_source_run_row,
    detect_structure_changes,
    promote_valid_changes,
    run_refresh_cycle,
    run_source_refresh,
)


def _row(structure_id="s1", stories=10, raw_source="nyc_pluto", geom=None):
    row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": structure_id,
            "PlaceGEOID": "3651000",
            "City": "Manhattan",
            "State": "New York",
            "StateFP": "36",
            "Country": "USA",
            "created_at": "2026-06-06T00:00:00+00:00",
            "updated_at": "2026-06-06T00:00:00+00:00",
            "updated_by": "unit_test",
            "change_log": "[]",
            "last_refreshed": "2026-06-06T00:00:00+00:00",
            "source_as_of": "2026-Q2",
            "CoverageTier": "Tier 1",
            "LoadSource": raw_source,
            "RawDataSource": raw_source,
            "FootprintSource": raw_source,
            "StructureType": "residential",
            "NumUnits": 12,
            "NumStories": stories,
            "FootprintArea_m2": 100.0,
            "FootprintArea_sqft": 1076.39,
            "OccupantCount": 24,
            "StructureTypeSource": raw_source,
            "StructureTypeConfidence": 0.95,
            "NumUnitsSource": raw_source,
            "NumUnitsConfidence": 0.95,
            "NumStoriesSource": raw_source,
            "NumStoriesConfidence": 0.95,
            "OccupantCountSource": raw_source,
            "OccupantCountMethod": "source",
            "OccupantCountConfidence": 0.95,
            "PredictionKind": pd.NA,
            "AIDisclosureLevel": pd.NA,
        }
    )
    return row, geom or box(0, 0, 0.001, 0.001)


def _frame(*rows):
    payloads = []
    geometries = []
    for item in rows:
        row, geometry = item
        payloads.append(row)
        geometries.append(geometry)
    return gpd.GeoDataFrame(payloads, geometry=geometries, crs="EPSG:4326")


def _config(**overrides):
    defaults = {
        "refresh_source_family": "assessor",
        "refresh_source_as_of": "2026-Q2",
        "refresh_cadence": "quarterly",
        "data_refresh_timestamp": "2026-06-06T12:00:00+00:00",
        "refresh_city": "Manhattan",
        "refresh_state": "New York",
        "promote_to_canonical": True,
    }
    defaults.update(overrides)
    return PipelineConfig(**defaults)


def test_source_run_metadata_and_raw_staging_shape():
    config = _config()
    source_run = build_source_run_row("nyc_pluto", "Manhattan", "New York", config, row_count=1)
    raw_rows = build_raw_structure_rows(_frame(_row()), source_run, config)

    assert source_run["source_name"] == "nyc_pluto"
    assert source_run["source_family"] == "assessor"
    assert source_run["source_as_of"] == "2026-Q2"
    assert source_run["data_refresh_timestamp"] == "2026-06-06T12:00:00+00:00"
    assert raw_rows[0]["source_run_id"] == source_run["source_run_id"]
    assert raw_rows[0]["raw_data_source"] == "nyc_pluto"
    assert raw_rows[0]["geometry_wkt"].startswith("POLYGON")
    assert raw_rows[0]["raw_payload"]["StructureID"] == "s1"
    assert raw_rows[0]["data_refresh_timestamp"] == "2026-06-06T12:00:00+00:00"


def test_change_detector_records_insert_update_unchanged_and_delete_candidate():
    store = InMemoryRefreshStore()
    config = _config()
    store.upsert_canonical_rows(
        [
            {**_row("same", stories=10)[0], "geometry_wkt": _row("same")[1].wkt},
            {**_row("changed", stories=5)[0], "geometry_wkt": _row("changed")[1].wkt},
            {**_row("missing", stories=2)[0], "geometry_wkt": box(3, 3, 3.001, 3.001).wkt},
        ]
    )
    staged = _frame(
        _row("new", geom=box(1, 1, 1.001, 1.001)),
        _row("same", stories=10),
        _row("changed", stories=12),
    )
    refresh = run_source_refresh("nyc_pluto", "Manhattan", "New York", config, source_frame=staged, store=store)

    result = detect_structure_changes(refresh["source_run"]["source_run_id"], config, store=store)

    counts = pd.Series([row["change_type"] for row in result["changes"]]).value_counts().to_dict()
    assert counts == {"insert": 1, "unchanged": 1, "update": 1, "delete_candidate": 1}
    assert all(row["data_refresh_timestamp"] == "2026-06-06T12:00:00+00:00" for row in result["changes"])
    update = next(row for row in result["changes"] if row["change_type"] == "update")
    assert "NumStories" in update["changed_fields"]


def test_promotion_blocks_failed_qa_and_keeps_canonical_unmutated():
    store = InMemoryRefreshStore()
    config = _config()
    bad_row, geometry = _row("bad", raw_source="ml_inference")
    refresh = run_source_refresh(
        "ai_predictions",
        "Manhattan",
        "New York",
        config,
        source_frame=_frame((bad_row, geometry)),
        store=store,
    )
    source_run_id = refresh["source_run"]["source_run_id"]
    detect_structure_changes(source_run_id, config, store=store)

    result = promote_valid_changes(source_run_id, config, store=store)

    assert result["promoted_count"] == 0
    assert result["failed_count"] == 1
    assert store.canonical_rows() == []
    assert len(store.promotion_failures) == 1
    assert store.promotion_failures[0]["source_run_id"] == source_run_id


def test_dry_run_does_not_mutate_store():
    store = InMemoryRefreshStore()
    config = _config(dry_run=True)

    result = run_source_refresh("overture", "Manhattan", "New York", config, source_frame=_frame(_row()), store=store)

    assert len(result["raw_rows"]) == 1
    assert store.raw_rows_for_run(result["source_run"]["source_run_id"]) == []
    assert store.source_runs == {}


def test_full_refresh_cycle_dry_run_computes_changes_without_mutating_store():
    store = InMemoryRefreshStore()
    config = _config(dry_run=True)

    result = run_refresh_cycle("nyc_pluto", "Manhattan", "New York", config, source_frame=_frame(_row()), store=store)

    assert len(result["raw_rows"]) == 1
    assert [row["change_type"] for row in result["changes"]] == ["insert"]
    assert result["promotion"]["promoted_count"] == 1
    assert store.raw_structures == []
    assert store.canonical_rows() == []
    assert store.release_manifests == {}


def test_full_refresh_cycle_promotes_valid_rows_and_writes_metadata():
    store = InMemoryRefreshStore()
    config = _config(release_id="refresh-test")

    result = run_refresh_cycle("nyc_pluto", "Manhattan", "New York", config, source_frame=_frame(_row()), store=store)

    assert result["source_run"]["status"] == "completed"
    assert result["promotion"]["promoted_count"] == 1
    assert len(store.canonical_rows()) == 1
    assert store.canonical_rows()[0]["data_refresh_timestamp"] == "2026-06-06T12:00:00+00:00"
    assert store.canonical_rows()[0]["StructureTypeSource"] == "nyc_pluto"
    assert store.canonical_rows()[0]["NumStoriesSource"] == "nyc_pluto"
    assert store.canonical_rows()[0]["NumUnitsSource"] == "nyc_pluto"
    assert store.canonical_rows()[0]["OccupantCountSource"] == "nyc_pluto"
    assert ("Manhattan", "New York") in store.coverage_registry
    assert store.coverage_registry[("Manhattan", "New York")]["data_refresh_timestamp"] == "2026-06-06T12:00:00+00:00"
    assert result["release_manifest"]["source_run"]["source_run_id"] == result["source_run"]["source_run_id"]
    assert result["release_manifest"]["refresh_status"] == "completed"
    assert result["release_manifest"]["data_refresh_timestamp"] == "2026-06-06T12:00:00+00:00"
