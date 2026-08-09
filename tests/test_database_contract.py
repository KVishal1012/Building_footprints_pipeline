from pathlib import Path

from structures_pipeline.database_contract import (
    CANONICAL_DATABASE_PLATFORM,
    database_contract,
    supabase_schema_sql,
)


def test_database_contract_marks_supabase_as_canonical_platform():
    tables = database_contract()

    assert CANONICAL_DATABASE_PLATFORM == "supabase_postgres"
    assert any(table["name"] == "public.structures" for table in tables)
    assert any(table["role"] == "canonical_source_of_truth" for table in tables)
    assert any(table["name"] == "staging.structure_observations" for table in tables)
    assert any(table["name"] == "history.structure_versions" for table in tables)
    assert any(table["name"] == "staging.promotion_failures" for table in tables)


def test_supabase_schema_sql_contains_required_tables_and_gates():
    sql = supabase_schema_sql().lower()

    assert "create schema if not exists staging" in sql
    assert "create table if not exists staging.source_objects" in sql
    assert "create table if not exists staging.structure_observations" in sql
    assert "create table if not exists staging.structure_changes" in sql
    assert "create table if not exists staging.promotion_failures" in sql
    assert "create table if not exists public.structures" in sql
    assert "coverage_tier text not null" in sql
    assert "data_refresh_timestamp timestamptz not null" in sql
    assert "structure_type_source text" in sql
    assert "num_units_source text" in sql
    assert "num_stories_source text" in sql
    assert "occupant_count_source text" in sql
    assert "attribute_provenance jsonb" in sql
    assert "ai_suggestions jsonb" in sql
    assert "using gist (geom)" in sql
    assert "partition by hash (city, source_run_id)" in sql


def test_supabase_refresh_migration_contains_live_schema_contract():
    migration = Path("migrations/001_supabase_refresh_schema.sql").read_text().lower()

    assert "create table if not exists staging.source_runs" in migration
    assert "create table if not exists public.structures" in migration
    assert "structure_type_source text" in migration
    assert "num_stories_source text" in migration
    assert "num_units_source text" in migration
    assert "occupant_count_source text" in migration
    assert "data_refresh_timestamp timestamptz not null" in migration


def test_chennai_lifecycle_migration_has_atomic_and_security_gates():
    sql = Path("migrations/002_chennai_refresh_lifecycle.sql").read_text().lower()

    assert "staging.promotion_candidates" in sql
    assert "finalize_structure_refresh" in sql
    assert "security invoker" in sql
    assert "security definer" not in sql
    assert "service_role is required" in sql
    assert "enable row level security" in sql
    assert "structures_ai_not_authoritative" in sql
    assert "source_run_id, raw_record_id" in sql


def test_compact_foundation_migration_enforces_storage_postgis_and_passports():
    sql = Path("migrations/003_compact_structure_foundation_and_passports.sql").read_text().lower()

    assert "structure-source-archives" in sql
    assert "create extension if not exists postgis" in sql
    assert "staging.structure_observations" in sql
    assert "raw_payload" not in sql
    assert "before_payload" not in sql
    assert "after_payload" not in sql
    assert "field_deltas jsonb" in sql
    assert "using gist (geom)" in sql
    assert "partition by hash (city, source_run_id)" in sql
    assert "staging.promotion_batches" in sql
    assert "promote_structure_batch_v3" in sql
    assert "history.archive_manifests" in sql
    assert "verified archive manifest is required" in sql
    assert "get_structure_passport" in sql
    assert "structure_ai_suggestions" in sql
    assert "security definer" not in sql
    assert "set geometry_wkt = null\n    where geometry_wkt is not null" in sql


def test_staging_rpc_does_not_reference_promotion_parameters():
    sql = Path("migrations/003_compact_structure_foundation_and_passports.sql").read_text().lower()
    staging_function = sql.split(
        "create or replace function staging.stage_structure_observations", 1
    )[1].split("create or replace function public.promote_structure_batch_v3", 1)[0]

    assert "p_source_run_id" not in staging_function
    assert "p_batch_number" not in staging_function
    assert "p_batch_hash" not in staging_function
