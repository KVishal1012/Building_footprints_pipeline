from __future__ import annotations

import argparse
from pathlib import Path

import scripts.run_chennai_refresh as chennai_refresh
from structures_pipeline.india import (
    build_india_refresh_config,
    default_source_path,
    get_tamil_nadu_city,
    india_source_registry_rows,
    tamil_nadu_city_registry_rows,
)


def test_tamil_nadu_registry_is_chennai_first_without_bengaluru():
    rows = tamil_nadu_city_registry_rows()
    cities = [row["city"] for row in rows]

    assert cities[0] == "Chennai"
    assert "Bengaluru" not in cities
    assert {"Coimbatore", "Madurai", "Tiruchirappalli", "Salem", "Tiruppur"} <= set(cities)
    assert rows[0]["status"] == "active_proof_market"
    assert rows[0]["default_source_file"] == "examples/india_chennai_refresh_source.csv"


def test_india_refresh_config_uses_chennai_source_defaults():
    config = build_india_refresh_config(
        city_slug="chennai",
        data_refresh_timestamp="2026-06-23T12:00:00+00:00",
    )

    assert config.country == "India"
    assert config.refresh_city == "Chennai"
    assert config.refresh_state == "Tamil Nadu"
    assert config.refresh_source_name == "chennai_overture_osm_fallback"
    assert config.refresh_source_family == "overture_osm_fallback"
    assert config.refresh_metadata["branch"] == "India_Structure_AI"
    assert config.refresh_metadata["coverage_tier"] == "Tier 4"
    assert config.refresh_metadata["last_refreshed"] == "2026-06-23T12:00:00+00:00"


def test_default_source_path_points_to_committed_chennai_fixture():
    path = default_source_path("chennai")

    assert path == Path("examples/india_chennai_refresh_source.csv")
    assert path.exists()
    assert get_tamil_nadu_city("Chennai").slug == "chennai"


def test_india_source_registry_has_no_ai_authoritative_source():
    for row in india_source_registry_rows():
        text = " ".join(str(value).lower() for value in row.values())
        assert row["source_name"].lower() not in {"ai", "ai_prediction", "ml_inference"}
        assert "prediction" not in text
        assert row["treatment"] in {
            "footprint_and_fallback",
            "authoritative_when_acquired",
        }


def test_chennai_refresh_runner_executes_local_refresh_cycle():
    args = argparse.Namespace(
        source_file="examples/india_chennai_refresh_source.csv",
        source_name="chennai_overture_osm_fallback",
        source_as_of="2026-Q2",
        data_refresh_timestamp="2026-06-23T12:00:00+00:00",
        store="in_memory",
        supabase_url=None,
        supabase_service_role_env="SUPABASE_SERVICE_ROLE_KEY",
        dry_run=False,
        no_promote=False,
        include_registries=True,
    )

    result = chennai_refresh.run_chennai_refresh(args)
    summary = chennai_refresh.build_summary(result, source_name=args.source_name, include_registries=True)

    assert summary["city"] == "Chennai"
    assert summary["state"] == "Tamil Nadu"
    assert summary["raw_rows"] == 3
    assert summary["promoted_count"] == 3
    assert summary["failed_count"] == 0
    assert summary["release_gate_status"] == "passed"
    assert summary["change_counts"] == {"insert": 3}
    assert summary["source_family"] == "overture_osm_fallback"
    assert "Coimbatore" in summary["tamil_nadu_expansion_targets"]
    assert result["release_manifest"]["branch"] == "India_Structure_AI"
