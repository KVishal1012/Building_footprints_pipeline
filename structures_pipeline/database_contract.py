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
        name="staging.source_objects",
        role="source_archive_index",
        description="Checksummed references to immutable source files in private object storage.",
    ),
    DatabaseTable(
        name="staging.structure_observations",
        role="normalized_staging",
        description="Normalized source observations with native PostGIS geometry and no raw payload copy.",
    ),
    DatabaseTable(
        name="staging.source_runs",
        role="ingestion_metadata",
        description="One row per source ingestion run, with source vintage and status.",
    ),
    DatabaseTable(
        name="staging.structure_changes",
        role="delta_logic",
        description="Compact field-level deltas, checksums, and geometry-change markers.",
    ),
    DatabaseTable(
        name="staging.promotion_failures",
        role="qa_failures",
        description="Rows blocked by QA/provenance gates before canonical promotion.",
    ),
    DatabaseTable(
        name="staging.promotion_batches",
        role="transaction_ledger",
        description="Idempotent bounded promotion batch status without duplicated canonical payloads.",
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
    DatabaseTable(
        name="history.structure_versions",
        role="partitioned_history",
        description="City and source-run partitioned canonical versions and geometry history.",
    ),
    DatabaseTable(
        name="public.structure_conflicts",
        role="passport_conflicts",
        description="Unresolved field-level disagreements between sources.",
    ),
    DatabaseTable(
        name="public.structure_quality_issues",
        role="passport_quality",
        description="QA status, warnings, and their resolution history.",
    ),
    DatabaseTable(
        name="public.structure_relationships",
        role="passport_relationships",
        description="Parcel, ward, hazard, and infrastructure relationships.",
    ),
    DatabaseTable(
        name="public.structure_ai_suggestions",
        role="passport_ai",
        description="Suggest-only model output stored separately from authoritative attributes.",
    ),
)


# Return the canonical Supabase/Postgres table contract as JSON-safe dictionaries.
def database_contract() -> list[dict]:
    """Return the canonical Supabase/Postgres table contract as JSON-safe dictionaries."""
    return [table.__dict__.copy() for table in DATABASE_TABLES]


# Return SQL DDL for the Supabase/Postgres staging and canonical tables.
def supabase_schema_sql() -> str:
    """Return the current compact Supabase/Postgres contract used by new refreshes."""
    return """
create schema if not exists staging;
create schema if not exists history;
create schema if not exists extensions;
create extension if not exists postgis with schema extensions;

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

create table if not exists staging.source_objects (
    source_object_id text primary key,
    bucket_id text not null,
    object_path text not null,
    object_uri text not null unique,
    checksum_sha256 text not null,
    content_type text,
    byte_size bigint,
    archive_status text not null,
    uploaded_at timestamptz not null default now()
);

create table if not exists staging.structure_observations (
    source_run_id text not null references staging.source_runs(source_run_id),
    raw_record_id text not null,
    source_object_id text not null references staging.source_objects(source_object_id),
    structure_id text not null,
    record_checksum text not null,
    raw_data_source text not null,
    source_authority text,
    source_family text not null,
    source_as_of text,
    city text,
    state text,
    geom extensions.geometry(Geometry, 4326) not null,
    loaded_at timestamptz not null default now(),
    data_refresh_timestamp timestamptz not null,
    primary key (source_run_id, raw_record_id)
);
create index if not exists structure_observations_geom_gix
on staging.structure_observations using gist (geom);

create table if not exists staging.structure_changes (
    change_id text primary key,
    structure_id text,
    source_run_id text references staging.source_runs(source_run_id),
    change_type text not null,
    changed_fields jsonb not null default '[]'::jsonb,
    field_deltas jsonb not null default '{}'::jsonb,
    before_checksum text,
    after_checksum text,
    geometry_changed boolean not null default false,
    detected_at timestamptz not null default now(),
    data_refresh_timestamp timestamptz
);

create table if not exists staging.promotion_failures (
    failure_id text primary key,
    source_run_id text references staging.source_runs(source_run_id),
    structure_id text,
    reason text not null,
    source_record_id text,
    detected_at timestamptz not null default now(),
    data_refresh_timestamp timestamptz
);

create table if not exists staging.promotion_batches (
    source_run_id text not null references staging.source_runs(source_run_id),
    batch_number integer not null,
    batch_hash text not null,
    row_count integer not null,
    status text not null,
    primary key (source_run_id, batch_number)
);

create table if not exists public.structures (
    structure_id text primary key,
    city text not null,
    state text not null,
    country text not null default 'USA',
    coverage_tier text not null,
    geometry_wkt text not null,
    geom extensions.geometry(Geometry, 4326),
    record_checksum text,
    qa_status text not null default 'passed',
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
create index if not exists structures_geom_gix
on public.structures using gist (geom);

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

create table if not exists history.structure_versions (
    version_id bigint generated always as identity,
    structure_id text not null,
    city text not null,
    source_run_id text not null,
    record_checksum text not null,
    geom extensions.geometry(Geometry, 4326) not null,
    recorded_at timestamptz not null default now(),
    primary key (city, source_run_id, version_id)
) partition by hash (city, source_run_id);

create table if not exists public.structure_conflicts (
    conflict_id bigint generated always as identity primary key,
    structure_id text not null,
    attribute_name text not null,
    status text not null default 'open'
);

create table if not exists public.structure_quality_issues (
    issue_id bigint generated always as identity primary key,
    structure_id text not null,
    severity text not null,
    status text not null default 'open',
    message text not null
);

create table if not exists public.structure_relationships (
    relationship_id bigint generated always as identity primary key,
    structure_id text not null,
    relationship_type text not null,
    related_record_id text not null
);

create table if not exists public.structure_ai_suggestions (
    suggestion_id bigint generated always as identity primary key,
    structure_id text not null,
    attribute_name text not null,
    suggested_value jsonb not null,
    confidence numeric not null,
    status text not null default 'suggested'
);
""".strip()
