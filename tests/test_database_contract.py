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


def test_supabase_schema_sql_contains_required_tables_and_gates():
    sql = supabase_schema_sql().lower()

    assert "create schema if not exists staging" in sql
    assert "create table if not exists staging.raw_structures" in sql
    assert "create table if not exists staging.change_log" in sql
    assert "create table if not exists public.structures" in sql
    assert "coverage_tier text not null" in sql
    assert "attribute_provenance jsonb" in sql
    assert "ai_suggestions jsonb" in sql
