from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseTable:
    name: str
    role: str
    description: str


CANONICAL_DATABASE_PLATFORM = "supabase_postgres"

DATABASE_TABLES = (
    DatabaseTable(
        name="staging.raw_structures",
        role="raw_drop",
        description="Raw upstream records and source snapshots before QA normalization.",
    ),
    DatabaseTable(
        name="staging.source_runs",
        role="ingestion_metadata",
        description="One row per source ingestion run, with source vintage and status.",
    ),
    DatabaseTable(
        name="staging.change_log",
        role="delta_logic",
        description="Detected inserts, updates, deletes, and source-to-canonical changes.",
    ),
    DatabaseTable(
        name="staging.promotion_failures",
        role="qa_failures",
        description="Rows blocked by QA/provenance gates before canonical promotion.",
    ),
    DatabaseTable(
        name="staging.promotion_candidates",
        role="atomic_promotion_staging",
        description="QA-approved rows held until one transaction finalizes the city refresh.",
    ),
    DatabaseTable(
        name="public.structures",
        role="canonical_source_of_truth",
        description="Approved canonical structure database exposed through Supabase APIs.",
    ),
    DatabaseTable(
        name="public.coverage_registry",
        role="coverage_metadata",
        description="City/source coverage tier, completeness, and gap metrics.",
    ),
    DatabaseTable(
        name="public.release_manifest",
        role="release_metadata",
        description="Versioned release package metadata and delivery manifest snapshots.",
    ),
)


# Return the canonical Supabase/Postgres table contract as JSON-safe dictionaries.
def database_contract() -> list[dict]:
    """Return the canonical Supabase/Postgres table contract as JSON-safe dictionaries."""
    return [table.__dict__.copy() for table in DATABASE_TABLES]


# Return SQL DDL for the Supabase/Postgres staging and canonical tables.
def supabase_schema_sql() -> str:
    """Return SQL DDL for the Supabase/Postgres staging and canonical tables."""
    return """
create schema if not exists staging;

create table if not exists staging.source_runs (
    source_run_id text primary key,
    source_name text not null,
    source_family text not null,
    source_as_of text,
    refresh_cadence text,
    data_refresh_timestamp timestamptz not null,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    status text not null default 'running',
    row_count integer,
    metadata jsonb not null default '{}'::jsonb
);

create table if not exists staging.raw_structures (
    raw_record_id text primary key,
    source_run_id text references staging.source_runs(source_run_id),
    raw_data_source text not null,
    source_authority text,
    source_family text not null,
    source_as_of text,
    city text,
    state text,
    geometry_wkt text,
    raw_payload jsonb not null,
    loaded_at timestamptz not null default now(),
    data_refresh_timestamp timestamptz not null
);

create table if not exists staging.change_log (
    change_id text primary key,
    structure_id text,
    source_run_id text references staging.source_runs(source_run_id),
    change_type text not null,
    changed_fields jsonb not null default '[]'::jsonb,
    before_payload jsonb,
    after_payload jsonb,
    detected_at timestamptz not null default now(),
    data_refresh_timestamp timestamptz
);

create table if not exists staging.promotion_failures (
    failure_id text primary key,
    source_run_id text references staging.source_runs(source_run_id),
    structure_id text,
    reason text not null,
    failed_payload jsonb not null,
    detected_at timestamptz not null default now(),
    data_refresh_timestamp timestamptz
);

create table if not exists public.structures (
    structure_id text primary key,
    city text not null,
    state text not null,
    country text not null default 'USA',
    coverage_tier text not null,
    geometry_wkt text not null,
    structure_type text,
    structure_type_source text,
    structure_type_confidence numeric,
    num_units numeric,
    num_units_source text,
    num_units_confidence numeric,
    num_stories numeric,
    num_stories_source text,
    num_stories_confidence numeric,
    footprint_area_m2 numeric,
    footprint_area_sqft numeric,
    occupant_count numeric,
    occupant_count_source text,
    occupant_count_method text,
    occupant_count_confidence numeric,
    load_source text not null,
    raw_data_source text not null,
    footprint_source text,
    attribute_provenance jsonb not null default '{}'::jsonb,
    ai_suggestions jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    updated_by text not null,
    change_log jsonb not null default '[]'::jsonb,
    data_refresh_timestamp timestamptz not null,
    last_refreshed timestamptz not null,
    source_as_of text
);

create table if not exists public.coverage_registry (
    city text not null,
    state text not null,
    coverage_tier text not null,
    row_count integer not null,
    completeness jsonb not null default '{}'::jsonb,
    source_summary jsonb not null default '{}'::jsonb,
    data_refresh_timestamp timestamptz,
    last_refreshed timestamptz,
    source_as_of text,
    primary key (city, state)
);

create table if not exists public.release_manifest (
    release_id text primary key,
    generated_at timestamptz not null default now(),
    schema_version text not null,
    row_count integer not null,
    manifest jsonb not null
);
""".strip()
