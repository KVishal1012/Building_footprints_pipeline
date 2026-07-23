import pandas as pd

from structures_pipeline.config import PipelineConfig
from structures_pipeline.refresh import (
    InMemoryRefreshStore,
    SupabaseRefreshStore,
    build_refresh_store,
    canonical_row_from_db,
    canonical_row_to_db,
    coverage_row_to_db,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = "" if payload is None else "json"

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse()


def _config(**overrides):
    defaults = {
        "supabase_url": "https://example.supabase.co",
        "supabase_service_role_env": "SUPABASE_SERVICE_ROLE_KEY",
        "request_timeout_sec": 10,
    }
    defaults.update(overrides)
    return PipelineConfig(**defaults)


def test_build_refresh_store_uses_in_memory_for_dry_run_even_when_supabase_requested():
    store = build_refresh_store(_config(dry_run=True), "supabase")

    assert isinstance(store, InMemoryRefreshStore)


def test_supabase_source_run_upsert_uses_staging_profile_and_conflict_key():
    session = FakeSession()
    store = SupabaseRefreshStore(_config(), session=session, service_key="secret")

    store.upsert_source_run(
        {
            "source_run_id": "run-1",
            "source_name": "nyc_pluto",
            "source_family": "assessor",
            "source_as_of": "2026-Q2",
            "refresh_cadence": "quarterly",
            "data_refresh_timestamp": "2026-06-06T12:00:00+00:00",
            "started_at": "2026-06-06T12:00:00+00:00",
            "completed_at": None,
            "status": "running",
            "row_count": 1,
            "metadata": {},
        }
    )

    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/rest/v1/source_runs")
    assert call["headers"]["Content-Profile"] == "staging"
    assert call["params"]["on_conflict"] == "source_run_id"


def test_supabase_canonical_upsert_maps_attribute_datasource_columns():
    session = FakeSession()
    store = SupabaseRefreshStore(_config(), session=session, service_key="secret")

    store.upsert_canonical_rows(
        [
            {
                "StructureID": "s1",
                "City": "Manhattan",
                "State": "New York",
                "Country": "USA",
                "CoverageTier": "Tier 1",
                "geometry_wkt": "POLYGON ((0 0, 0 1, 1 1, 0 0))",
                "StructureType": "residential",
                "StructureTypeSource": "nyc_pluto_land_use",
                "StructureTypeConfidence": 0.95,
                "NumUnits": 12,
                "NumUnitsSource": "nyc_pluto_units_total",
                "NumUnitsConfidence": 0.95,
                "NumStories": 10,
                "NumStoriesSource": "nyc_pluto_num_floors",
                "NumStoriesConfidence": 0.95,
                "OccupantCount": 24,
                "OccupantCountSource": "nyc_pluto_occupancy",
                "OccupantCountMethod": "source",
                "OccupantCountConfidence": 0.95,
                "LoadSource": "nyc_pluto",
                "RawDataSource": "nyc_pluto",
                "FootprintSource": "nyc_pluto",
                "PredictedStructureType": pd.NA,
                "PredictionKind": pd.NA,
                "created_at": "2026-06-06T12:00:00+00:00",
                "updated_at": "2026-06-06T12:00:00+00:00",
                "updated_by": "unit_test",
                "change_log": "[]",
                "data_refresh_timestamp": "2026-06-06T12:00:00+00:00",
                "last_refreshed": "2026-06-06T12:00:00+00:00",
                "source_as_of": "2026-Q2",
            }
        ]
    )

    call = session.calls[0]
    payload = call["json"][0]
    assert call["url"].endswith("/rest/v1/structures")
    assert call["headers"]["Content-Profile"] == "public"
    assert call["params"]["on_conflict"] == "structure_id"
    assert payload["structure_id"] == "s1"
    assert payload["structure_type_source"] == "nyc_pluto_land_use"
    assert payload["num_stories_source"] == "nyc_pluto_num_floors"
    assert payload["num_units_source"] == "nyc_pluto_units_total"
    assert payload["occupant_count_source"] == "nyc_pluto_occupancy"
    assert payload["attribute_provenance"]["occupant_count"]["source"] == "nyc_pluto_occupancy"
    assert payload["ai_suggestions"]["prediction_kind"] is None


def test_supabase_canonical_select_converts_snake_case_to_pipeline_shape():
    session = FakeSession(
        responses=[
            FakeResponse(
                [
                    {
                        "structure_id": "s1",
                        "city": "Manhattan",
                        "state": "New York",
                        "structure_type": "residential",
                        "structure_type_source": "nyc_pluto_land_use",
                    }
                ]
            )
        ]
    )
    store = SupabaseRefreshStore(_config(), session=session, service_key="secret")

    rows = store.canonical_rows()

    assert rows[0]["StructureID"] == "s1"
    assert rows[0]["City"] == "Manhattan"
    assert rows[0]["StructureTypeSource"] == "nyc_pluto_land_use"
    assert session.calls[0]["headers"]["Accept-Profile"] == "public"


def test_payload_conversion_helpers_match_supabase_table_shapes():
    db_row = canonical_row_to_db(
        {
            "StructureID": "s1",
            "StructureTypeSource": "nyc_pluto_land_use",
            "NumStoriesSource": "nyc_pluto_num_floors",
            "NumUnitsSource": "nyc_pluto_units_total",
            "OccupantCountSource": "nyc_pluto_occupancy",
            "PredictionKind": pd.NA,
        }
    )
    coverage = coverage_row_to_db(
        {
            "City": "Manhattan",
            "State": "New York",
            "CoverageTier": "Tier 1",
            "row_count": 1,
            "structure_type_completeness": 1.0,
            "num_units_completeness": 1.0,
            "num_stories_completeness": 1.0,
            "occupant_count_completeness": 1.0,
            "has_authoritative_source": True,
        }
    )
    round_trip = canonical_row_from_db({"structure_id": "s1", "num_stories_source": "nyc_pluto_num_floors"})

    assert db_row["structure_type_source"] == "nyc_pluto_land_use"
    assert db_row["ai_suggestions"]["prediction_kind"] is None
    assert coverage["completeness"]["num_stories"] == 1.0
    assert coverage["source_summary"]["has_authoritative_source"] is True
    assert round_trip["StructureID"] == "s1"
    assert round_trip["NumStoriesSource"] == "nyc_pluto_num_floors"


def test_supabase_writes_large_payloads_in_bounded_batches():
    session = FakeSession()
    store = SupabaseRefreshStore(
        _config(supabase_batch_size=2),
        session=session,
        service_key="secret",
    )

    store.insert_raw_rows(
        {
            "source_run_id": "run-1",
            "raw_record_id": f"raw-{index}",
        }
        for index in range(5)
    )

    assert [len(call["json"]) for call in session.calls] == [2, 2, 1]
    assert all(
        call["params"]["on_conflict"] == "source_run_id,raw_record_id"
        for call in session.calls
    )


def test_supabase_reads_every_page():
    session = FakeSession(
        responses=[
            FakeResponse([{"structure_id": "s1"}, {"structure_id": "s2"}]),
            FakeResponse([{"structure_id": "s3"}]),
        ]
    )
    store = SupabaseRefreshStore(
        _config(supabase_page_size=2),
        session=session,
        service_key="secret",
    )

    rows = store.canonical_rows(city="Chennai", state="Tamil Nadu")

    assert [row["StructureID"] for row in rows] == ["s1", "s2", "s3"]
    assert session.calls[0]["params"]["offset"] == 0
    assert session.calls[1]["params"]["offset"] == 2
    assert session.calls[0]["params"]["city"] == "eq.Chennai"


def test_supabase_retries_transient_response():
    session = FakeSession(
        responses=[
            FakeResponse({"error": "busy"}, status_code=503),
            FakeResponse([]),
        ]
    )
    store = SupabaseRefreshStore(
        _config(supabase_retry_backoff_sec=0),
        session=session,
        service_key="secret",
    )

    assert store.canonical_rows() == []
    assert len(session.calls) == 2


def test_supabase_atomic_finalize_uses_service_rpc_payload():
    session = FakeSession()
    store = SupabaseRefreshStore(_config(), session=session, service_key="secret")

    store.finalize_refresh(
        "run-1",
        [
            {
                "City": "Chennai",
                "State": "Tamil Nadu",
                "CoverageTier": "Tier 4",
                "row_count": 1,
            }
        ],
        {
            "release_id": "release-1",
            "generated_at": "2026-07-23T12:00:00+00:00",
            "schema_version": "2.0",
            "row_count": 1,
        },
    )

    call = session.calls[0]
    assert call["url"].endswith("/rest/v1/rpc/finalize_structure_refresh")
    assert call["json"]["p_source_run_id"] == "run-1"
    assert call["json"]["p_release_manifest"]["release_id"] == "release-1"
