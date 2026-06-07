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
    assert any(table["name"] == "staging.raw_structures" for table in tables)
    assert any(table["name"] == "staging.promotion_failures" for table in tables)


def test_supabase_schema_sql_contains_required_tables_and_gates():
    sql = supabase_schema_sql().lower()

    assert "create schema if not exists staging" in sql
    assert "create table if not exists staging.raw_structures" in sql
    assert "create table if not exists staging.change_log" in sql
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


def test_supabase_refresh_migration_contains_live_schema_contract():
    migration = Path("migrations/001_supabase_refresh_schema.sql").read_text().lower()

    assert "create table if not exists staging.source_runs" in migration
    assert "create table if not exists public.structures" in migration
    assert "structure_type_source text" in migration
    assert "num_stories_source text" in migration
    assert "num_units_source text" in migration
    assert "occupant_count_source text" in migration
    assert "data_refresh_timestamp timestamptz not null" in migration
