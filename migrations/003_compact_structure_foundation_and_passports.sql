-- Compact, PostGIS-native refresh foundation and Structure Passport contract.
-- This migration is additive. Legacy raw/change/candidate tables remain available
-- for audit and rollback, but new refreshes write to the objects below.

create schema if not exists extensions;
create extension if not exists postgis with schema extensions;
create schema if not exists staging;
create schema if not exists history;

create table if not exists staging.source_objects (
    source_object_id text primary key,
    bucket_id text not null default 'structure-source-archives',
    object_path text not null,
    object_uri text not null unique,
    checksum_sha256 text not null check (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    content_type text,
    byte_size bigint check (byte_size is null or byte_size >= 0),
    source_as_of text,
    archive_status text not null default 'registered'
        check (archive_status in ('registered', 'verified', 'archived', 'failed')),
    uploaded_at timestamptz not null default now(),
    verified_at timestamptz,
    metadata jsonb not null default '{}'::jsonb
);

alter table staging.source_runs
    add column if not exists source_object_id text
        references staging.source_objects(source_object_id);

create table if not exists staging.structure_observations (
    source_run_id text not null references staging.source_runs(source_run_id),
    raw_record_id text not null,
    source_object_id text not null references staging.source_objects(source_object_id),
    source_row_number bigint,
    structure_id text not null,
    record_checksum text not null check (record_checksum ~ '^[0-9a-f]{64}$'),
    raw_data_source text not null,
    source_authority text not null,
    source_family text not null,
    provenance_tier text not null,
    source_as_of text not null,
    city text not null,
    state text not null,
    country text not null default 'India',
    coverage_tier text not null,
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
    footprint_source text,
    geom extensions.geometry(Geometry, 4326) not null,
    loaded_at timestamptz not null default now(),
    data_refresh_timestamp timestamptz not null,
    primary key (source_run_id, raw_record_id),
    constraint observation_geometry_valid check (extensions.st_isvalid(geom)),
    constraint observation_geometry_nonempty check (not extensions.st_isempty(geom))
);

create index if not exists structure_observations_run_idx
    on staging.structure_observations (source_run_id, raw_record_id);
create index if not exists structure_observations_structure_idx
    on staging.structure_observations (structure_id);
create index if not exists structure_observations_city_source_idx
    on staging.structure_observations (city, source_run_id);
create index if not exists structure_observations_geom_gix
    on staging.structure_observations using gist (geom);

create table if not exists staging.structure_changes (
    change_id text primary key,
    structure_id text,
    raw_record_id text,
    source_run_id text not null references staging.source_runs(source_run_id),
    city text not null,
    state text not null,
    change_type text not null
        check (change_type in ('insert', 'update', 'delete_candidate', 'unchanged')),
    changed_fields jsonb not null default '[]'::jsonb
        check (jsonb_typeof(changed_fields) = 'array'),
    field_deltas jsonb not null default '{}'::jsonb
        check (jsonb_typeof(field_deltas) = 'object'),
    before_checksum text,
    after_checksum text,
    geometry_changed boolean not null default false,
    detected_at timestamptz not null default now(),
    data_refresh_timestamp timestamptz not null
);

create index if not exists structure_changes_run_idx
    on staging.structure_changes (source_run_id, change_type);
create index if not exists structure_changes_structure_idx
    on staging.structure_changes (structure_id, detected_at desc);

alter table staging.promotion_failures
    add column if not exists source_record_id text;
alter table staging.promotion_failures
    alter column failed_payload drop not null;

create table if not exists staging.promotion_batches (
    source_run_id text not null references staging.source_runs(source_run_id),
    batch_number integer not null check (batch_number >= 0),
    batch_hash text not null check (batch_hash ~ '^[0-9a-f]{64}$'),
    row_count integer not null check (row_count >= 0),
    status text not null default 'pending'
        check (status in ('pending', 'running', 'completed', 'failed')),
    started_at timestamptz,
    completed_at timestamptz,
    error_message text,
    primary key (source_run_id, batch_number)
);

alter table public.structures
    add column if not exists geom extensions.geometry(Geometry, 4326),
    add column if not exists record_checksum text,
    add column if not exists qa_status text not null default 'passed';

update public.structures
set geom = extensions.st_geomfromtext(geometry_wkt, 4326)
where geom is null
  and geometry_wkt is not null;

alter table public.structures
    alter column geometry_wkt drop not null,
    drop constraint if exists structures_geom_valid,
    add constraint structures_geom_valid
        check (geom is null or extensions.st_isvalid(geom));

update public.structures
set geometry_wkt = null
where geom is not null;

create index if not exists structures_geom_gix
    on public.structures using gist (geom);
create index if not exists structures_city_state_idx
    on public.structures (city, state, structure_id);

create table if not exists history.structure_versions (
    version_id bigint generated always as identity,
    structure_id text not null,
    city text not null,
    state text not null,
    source_run_id text not null,
    source_object_id text references staging.source_objects(source_object_id),
    record_checksum text not null,
    change_type text not null,
    structure_type text,
    structure_type_source text,
    structure_type_confidence numeric,
    num_units numeric,
    num_units_source text,
    num_units_confidence numeric,
    num_stories numeric,
    num_stories_source text,
    num_stories_confidence numeric,
    occupant_count numeric,
    occupant_count_source text,
    occupant_count_method text,
    occupant_count_confidence numeric,
    source_as_of text,
    last_refreshed timestamptz,
    data_refresh_timestamp timestamptz not null,
    geom extensions.geometry(Geometry, 4326) not null,
    recorded_at timestamptz not null default now(),
    primary key (city, source_run_id, version_id)
) partition by hash (city, source_run_id);

do $$
declare
    partition_number integer;
begin
    for partition_number in 0..7 loop
        execute format(
            'create table if not exists history.structure_versions_p%s partition of history.structure_versions for values with (modulus 8, remainder %s)',
            partition_number,
            partition_number
        );
    end loop;
end
$$;

create index if not exists structure_versions_structure_idx
    on history.structure_versions (structure_id, recorded_at desc);
create index if not exists structure_versions_source_object_idx
    on history.structure_versions (source_object_id);
create index if not exists structure_versions_geom_gix
    on history.structure_versions using gist (geom);

create table if not exists public.structure_conflicts (
    conflict_id bigint generated always as identity primary key,
    structure_id text not null references public.structures(structure_id) on delete cascade,
    attribute_name text not null,
    canonical_value jsonb,
    conflicting_value jsonb,
    canonical_source text,
    conflicting_source text not null,
    source_run_id text,
    status text not null default 'open'
        check (status in ('open', 'accepted', 'rejected', 'resolved')),
    detected_at timestamptz not null default now(),
    resolved_at timestamptz,
    resolution_note text
);

create table if not exists public.structure_quality_issues (
    issue_id bigint generated always as identity primary key,
    structure_id text not null references public.structures(structure_id) on delete cascade,
    source_run_id text,
    check_name text not null,
    severity text not null check (severity in ('info', 'warning', 'error', 'blocker')),
    status text not null default 'open' check (status in ('open', 'resolved', 'waived')),
    message text not null,
    details jsonb not null default '{}'::jsonb,
    detected_at timestamptz not null default now(),
    resolved_at timestamptz
);

create table if not exists public.structure_relationships (
    relationship_id bigint generated always as identity primary key,
    structure_id text not null references public.structures(structure_id) on delete cascade,
    relationship_type text not null
        check (relationship_type in ('parcel', 'ward', 'hazard', 'infrastructure')),
    related_record_id text not null,
    related_source text not null,
    relationship_method text not null,
    confidence numeric,
    distance_m numeric,
    valid_from timestamptz not null default now(),
    valid_to timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    unique (structure_id, relationship_type, related_record_id, related_source)
);

create table if not exists public.structure_ai_suggestions (
    suggestion_id bigint generated always as identity primary key,
    structure_id text not null references public.structures(structure_id) on delete cascade,
    attribute_name text not null,
    suggested_value jsonb not null,
    model_name text not null,
    model_version text not null,
    prediction_kind text not null,
    confidence numeric not null check (confidence between 0 and 1),
    features_used jsonb not null default '[]'::jsonb,
    disclosure_level text not null,
    suppression_reason text,
    status text not null default 'suggested'
        check (status in ('suggested', 'suppressed', 'accepted', 'rejected', 'expired')),
    source_run_id text,
    created_at timestamptz not null default now()
);

create index if not exists structure_conflicts_open_idx
    on public.structure_conflicts (structure_id, status);
create index if not exists structure_quality_open_idx
    on public.structure_quality_issues (structure_id, status, severity);
create index if not exists structure_relationships_idx
    on public.structure_relationships (structure_id, relationship_type);
create index if not exists structure_ai_suggestions_idx
    on public.structure_ai_suggestions (structure_id, attribute_name, created_at desc);

create table if not exists history.archive_manifests (
    archive_manifest_id bigint generated always as identity primary key,
    table_name text not null,
    city text,
    source_run_id text,
    archive_uri text not null,
    checksum_sha256 text not null check (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    row_count bigint not null check (row_count >= 0),
    verified_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists staging.retention_policies (
    table_name text primary key,
    retention_days integer not null check (retention_days > 0),
    require_verified_archive boolean not null default true,
    enabled boolean not null default true,
    updated_at timestamptz not null default now()
);

insert into staging.retention_policies
    (table_name, retention_days, require_verified_archive)
values
    ('staging.structure_observations', 90, true),
    ('staging.structure_changes', 365, true),
    ('staging.promotion_batches', 90, true),
    ('history.structure_versions', 2555, true)
on conflict (table_name) do nothing;

create or replace function staging.stage_structure_observations(p_rows jsonb)
returns integer
language plpgsql
security invoker
set search_path = pg_catalog, staging, extensions
as $$
declare
    affected integer;
begin
    if current_user <> 'service_role' then
        raise exception 'service_role is required';
    end if;

    insert into staging.structure_observations (
        source_run_id, raw_record_id, source_object_id, source_row_number,
        structure_id, record_checksum, raw_data_source, source_authority,
        source_family, provenance_tier, source_as_of, city, state, country,
        coverage_tier, structure_type, structure_type_source,
        structure_type_confidence, num_units, num_units_source,
        num_units_confidence, num_stories, num_stories_source,
        num_stories_confidence, footprint_area_m2, footprint_area_sqft,
        occupant_count, occupant_count_source, occupant_count_method,
        occupant_count_confidence, load_source, footprint_source, geom,
        loaded_at, data_refresh_timestamp
    )
    select
        row.source_run_id, row.raw_record_id, row.source_object_id,
        row.source_row_number, row.structure_id, row.record_checksum,
        row.raw_data_source, row.source_authority, row.source_family,
        row.provenance_tier, row.source_as_of, row.city, row.state,
        coalesce(row.country, 'India'), row.coverage_tier, row.structure_type,
        row.structure_type_source, row.structure_type_confidence, row.num_units,
        row.num_units_source, row.num_units_confidence, row.num_stories,
        row.num_stories_source, row.num_stories_confidence,
        row.footprint_area_m2, row.footprint_area_sqft, row.occupant_count,
        row.occupant_count_source, row.occupant_count_method,
        row.occupant_count_confidence, row.load_source, row.footprint_source,
        extensions.st_geomfromtext(row.geometry_wkt, 4326),
        coalesce(row.loaded_at, now()), row.data_refresh_timestamp
    from jsonb_to_recordset(p_rows) as row(
        source_run_id text, raw_record_id text, source_object_id text,
        source_row_number bigint, structure_id text, record_checksum text,
        raw_data_source text, source_authority text, source_family text,
        provenance_tier text, source_as_of text, city text, state text,
        country text, coverage_tier text, structure_type text,
        structure_type_source text, structure_type_confidence numeric,
        num_units numeric, num_units_source text, num_units_confidence numeric,
        num_stories numeric, num_stories_source text,
        num_stories_confidence numeric, footprint_area_m2 numeric,
        footprint_area_sqft numeric, occupant_count numeric,
        occupant_count_source text, occupant_count_method text,
        occupant_count_confidence numeric, load_source text,
        footprint_source text, geometry_wkt text, loaded_at timestamptz,
        data_refresh_timestamp timestamptz
    )
    on conflict (source_run_id, raw_record_id) do update set
        source_object_id = excluded.source_object_id,
        record_checksum = excluded.record_checksum,
        geom = excluded.geom,
        loaded_at = excluded.loaded_at,
        data_refresh_timestamp = excluded.data_refresh_timestamp;

    get diagnostics affected = row_count;
    return affected;
end;
$$;

create or replace function public.promote_structure_batch_v3(
    p_source_run_id text,
    p_batch_number integer,
    p_batch_hash text,
    p_rows jsonb
)
returns integer
language plpgsql
security invoker
set search_path = pg_catalog, public, staging, history, extensions
as $$
declare
    affected integer;
    expected_rows integer := jsonb_array_length(p_rows);
begin
    if current_user <> 'service_role' then
        raise exception 'service_role is required';
    end if;

    if exists (
        select 1 from staging.promotion_batches
        where source_run_id = p_source_run_id
          and batch_number = p_batch_number
          and batch_hash <> p_batch_hash
    ) then
        raise exception 'promotion batch number was already used with a different payload';
    end if;

    insert into staging.promotion_batches (
        source_run_id, batch_number, batch_hash, row_count, status, started_at
    )
    values (
        p_source_run_id, p_batch_number, p_batch_hash, expected_rows, 'running', now()
    )
    on conflict (source_run_id, batch_number) do update set
        status = case
            when staging.promotion_batches.batch_hash = excluded.batch_hash
             and staging.promotion_batches.status = 'completed'
            then 'completed' else 'running' end,
        batch_hash = excluded.batch_hash,
        row_count = excluded.row_count,
        started_at = now(),
        error_message = null;

    if exists (
        select 1 from staging.promotion_batches
        where source_run_id = p_source_run_id
          and batch_number = p_batch_number
          and batch_hash = p_batch_hash
          and status = 'completed'
    ) then
        return expected_rows;
    end if;

    create temporary table if not exists refresh_batch_rows (
        like public.structures including defaults
    ) on commit drop;
    truncate refresh_batch_rows;

    insert into refresh_batch_rows
    select populated.*
    from jsonb_populate_recordset(null::public.structures, p_rows) populated;

    update refresh_batch_rows
    set geom = extensions.st_geomfromtext(geometry_wkt, 4326)
    where geom is null and geometry_wkt is not null;

    if exists (
        select 1 from refresh_batch_rows
        where structure_id is null or geom is null
           or extensions.st_isempty(geom) or not extensions.st_isvalid(geom)
    ) then
        raise exception 'promotion batch contains missing or invalid identity/geometry';
    end if;

    update refresh_batch_rows
    set geometry_wkt = null
    where geometry_wkt is not null;

    insert into public.structures
    select * from refresh_batch_rows
    on conflict (structure_id) do update set
        city = excluded.city,
        state = excluded.state,
        country = excluded.country,
        coverage_tier = excluded.coverage_tier,
        geometry_wkt = excluded.geometry_wkt,
        geom = excluded.geom,
        record_checksum = excluded.record_checksum,
        qa_status = excluded.qa_status,
        structure_type = excluded.structure_type,
        structure_type_source = excluded.structure_type_source,
        structure_type_confidence = excluded.structure_type_confidence,
        num_units = excluded.num_units,
        num_units_source = excluded.num_units_source,
        num_units_confidence = excluded.num_units_confidence,
        num_stories = excluded.num_stories,
        num_stories_source = excluded.num_stories_source,
        num_stories_confidence = excluded.num_stories_confidence,
        footprint_area_m2 = excluded.footprint_area_m2,
        footprint_area_sqft = excluded.footprint_area_sqft,
        occupant_count = excluded.occupant_count,
        occupant_count_source = excluded.occupant_count_source,
        occupant_count_method = excluded.occupant_count_method,
        occupant_count_confidence = excluded.occupant_count_confidence,
        load_source = excluded.load_source,
        raw_data_source = excluded.raw_data_source,
        footprint_source = excluded.footprint_source,
        attribute_provenance = excluded.attribute_provenance,
        ai_suggestions = '{}'::jsonb,
        updated_at = excluded.updated_at,
        updated_by = excluded.updated_by,
        change_log = excluded.change_log,
        data_refresh_timestamp = excluded.data_refresh_timestamp,
        last_refreshed = excluded.last_refreshed,
        source_as_of = excluded.source_as_of,
        source_authority = excluded.source_authority,
        source_family = excluded.source_family,
        provenance_tier = excluded.provenance_tier,
        source_run_id = excluded.source_run_id;

    get diagnostics affected = row_count;

    insert into history.structure_versions (
        structure_id, city, state, source_run_id, source_object_id,
        record_checksum, change_type, structure_type, structure_type_source,
        structure_type_confidence, num_units, num_units_source,
        num_units_confidence, num_stories, num_stories_source,
        num_stories_confidence, occupant_count, occupant_count_source,
        occupant_count_method, occupant_count_confidence, source_as_of,
        last_refreshed, data_refresh_timestamp, geom
    )
    select
        row.structure_id, row.city, row.state, p_source_run_id, run.source_object_id,
        row.record_checksum, 'promoted', row.structure_type,
        row.structure_type_source, row.structure_type_confidence, row.num_units,
        row.num_units_source, row.num_units_confidence, row.num_stories,
        row.num_stories_source, row.num_stories_confidence, row.occupant_count,
        row.occupant_count_source, row.occupant_count_method,
        row.occupant_count_confidence, row.source_as_of, row.last_refreshed,
        row.data_refresh_timestamp, row.geom
    from refresh_batch_rows row
    join staging.source_runs run on run.source_run_id = p_source_run_id;

    update staging.promotion_batches
    set status = 'completed', completed_at = now()
    where source_run_id = p_source_run_id
      and batch_number = p_batch_number;

    return affected;
exception
    when others then
        update staging.promotion_batches
        set status = 'failed', completed_at = now(), error_message = sqlerrm
        where source_run_id = p_source_run_id
          and batch_number = p_batch_number;
        raise;
end;
$$;

create or replace function public.finalize_structure_refresh_v3(
    p_source_run_id text,
    p_expected_promoted_count integer,
    p_coverage_rows jsonb,
    p_release_manifest jsonb
)
returns void
language plpgsql
security invoker
set search_path = pg_catalog, public, staging
as $$
declare
    completed_rows bigint;
begin
    if current_user <> 'service_role' then
        raise exception 'service_role is required';
    end if;

    select coalesce(sum(row_count), 0)
    into completed_rows
    from staging.promotion_batches
    where source_run_id = p_source_run_id
      and status = 'completed';

    if completed_rows <> p_expected_promoted_count then
        raise exception
            'completed promotion rows (%) do not match expected rows (%)',
            completed_rows, p_expected_promoted_count;
    end if;
    if exists (
        select 1 from staging.promotion_batches
        where source_run_id = p_source_run_id and status <> 'completed'
    ) then
        raise exception 'refresh has incomplete promotion batches';
    end if;

    insert into public.coverage_registry (
        city, state, coverage_tier, row_count, completeness, source_summary,
        data_refresh_timestamp, last_refreshed, source_as_of
    )
    select
        row.city, row.state, row.coverage_tier, row.row_count,
        coalesce(row.completeness, '{}'::jsonb),
        coalesce(row.source_summary, '{}'::jsonb),
        row.data_refresh_timestamp, row.last_refreshed, row.source_as_of
    from jsonb_to_recordset(p_coverage_rows) as row(
        city text, state text, coverage_tier text, row_count integer,
        completeness jsonb, source_summary jsonb,
        data_refresh_timestamp timestamptz, last_refreshed timestamptz,
        source_as_of text
    )
    on conflict (city, state) do update set
        coverage_tier = excluded.coverage_tier,
        row_count = excluded.row_count,
        completeness = excluded.completeness,
        source_summary = excluded.source_summary,
        data_refresh_timestamp = excluded.data_refresh_timestamp,
        last_refreshed = excluded.last_refreshed,
        source_as_of = excluded.source_as_of;

    insert into public.release_manifest (
        release_id, generated_at, schema_version, row_count, manifest
    )
    values (
        p_release_manifest->>'release_id',
        coalesce((p_release_manifest->>'generated_at')::timestamptz, now()),
        coalesce(p_release_manifest->>'schema_version', '3.0'),
        coalesce((p_release_manifest->>'row_count')::integer, 0),
        p_release_manifest->'manifest'
    )
    on conflict (release_id) do update set
        generated_at = excluded.generated_at,
        schema_version = excluded.schema_version,
        row_count = excluded.row_count,
        manifest = excluded.manifest;

    update staging.source_runs
    set status = 'completed', completed_at = now()
    where source_run_id = p_source_run_id;
end;
$$;

create or replace function public.get_structure_passport(p_structure_id text)
returns jsonb
language sql
stable
security invoker
set search_path = pg_catalog, public, staging, history, extensions
as $$
    select jsonb_build_object(
        'schema_version', '1.0',
        'structure_id', current.structure_id,
        'current', to_jsonb(current) - 'ai_suggestions',
        'attributes', jsonb_build_object(
            'structure_type', jsonb_build_object(
                'value', current.structure_type,
                'source', current.structure_type_source,
                'confidence', current.structure_type_confidence
            ),
            'num_stories', jsonb_build_object(
                'value', current.num_stories,
                'source', current.num_stories_source,
                'confidence', current.num_stories_confidence
            ),
            'num_units', jsonb_build_object(
                'value', current.num_units,
                'source', current.num_units_source,
                'confidence', current.num_units_confidence
            ),
            'occupant_count', jsonb_build_object(
                'value', current.occupant_count,
                'source', current.occupant_count_source,
                'method', current.occupant_count_method,
                'confidence', current.occupant_count_confidence
            )
        ),
        'freshness', jsonb_build_object(
            'source_as_of', current.source_as_of,
            'last_refreshed', current.last_refreshed,
            'data_refresh_timestamp', current.data_refresh_timestamp
        ),
        'geometry', jsonb_build_object(
            'current_geojson', extensions.st_asgeojson(current.geom)::jsonb,
            'history', coalesce((
                select jsonb_agg(to_jsonb(version) order by version.recorded_at desc)
                from (
                    select source_run_id, record_checksum, source_as_of,
                           recorded_at, extensions.st_asgeojson(geom)::jsonb as geometry
                    from history.structure_versions
                    where structure_id = current.structure_id
                    order by recorded_at desc limit 100
                ) version
            ), '[]'::jsonb)
        ),
        'conflicts', coalesce((
            select jsonb_agg(to_jsonb(conflict) order by detected_at desc)
            from public.structure_conflicts conflict
            where conflict.structure_id = current.structure_id
        ), '[]'::jsonb),
        'change_timeline', coalesce((
            select jsonb_agg(to_jsonb(change) order by detected_at desc)
            from (
                select change_type, changed_fields, field_deltas,
                       source_run_id, detected_at
                from staging.structure_changes
                where structure_id = current.structure_id
                order by detected_at desc limit 100
            ) change
        ), '[]'::jsonb),
        'ai_suggestions', coalesce((
            select jsonb_agg(to_jsonb(suggestion) order by created_at desc)
            from public.structure_ai_suggestions suggestion
            where suggestion.structure_id = current.structure_id
        ), '[]'::jsonb),
        'qa', jsonb_build_object(
            'status', current.qa_status,
            'issues', coalesce((
                select jsonb_agg(to_jsonb(issue) order by detected_at desc)
                from public.structure_quality_issues issue
                where issue.structure_id = current.structure_id
            ), '[]'::jsonb)
        ),
        'relationships', jsonb_build_object(
            'parcel', coalesce((select jsonb_agg(to_jsonb(r)) from public.structure_relationships r where r.structure_id = current.structure_id and relationship_type = 'parcel' and valid_to is null), '[]'::jsonb),
            'ward', coalesce((select jsonb_agg(to_jsonb(r)) from public.structure_relationships r where r.structure_id = current.structure_id and relationship_type = 'ward' and valid_to is null), '[]'::jsonb),
            'hazard', coalesce((select jsonb_agg(to_jsonb(r)) from public.structure_relationships r where r.structure_id = current.structure_id and relationship_type = 'hazard' and valid_to is null), '[]'::jsonb),
            'infrastructure', coalesce((select jsonb_agg(to_jsonb(r)) from public.structure_relationships r where r.structure_id = current.structure_id and relationship_type = 'infrastructure' and valid_to is null), '[]'::jsonb)
        )
    )
    from public.structures current
    where current.structure_id = p_structure_id;
$$;

create or replace function staging.purge_verified_archives(
    p_table_name text,
    p_city text,
    p_source_run_id text
)
returns bigint
language plpgsql
security invoker
set search_path = pg_catalog, staging, history
as $$
declare
    deleted_rows bigint;
begin
    if current_user <> 'service_role' then
        raise exception 'service_role is required';
    end if;
    if not exists (
        select 1 from history.archive_manifests
        where table_name = p_table_name
          and city is not distinct from p_city
          and source_run_id is not distinct from p_source_run_id
          and verified_at is not null
    ) then
        raise exception 'verified archive manifest is required before retention purge';
    end if;

    if p_table_name = 'staging.structure_observations' then
        delete from staging.structure_observations
        where source_run_id = p_source_run_id and city = p_city;
    elsif p_table_name = 'staging.structure_changes' then
        delete from staging.structure_changes
        where source_run_id = p_source_run_id and city = p_city;
    elsif p_table_name = 'staging.promotion_batches' then
        delete from staging.promotion_batches where source_run_id = p_source_run_id;
    elsif p_table_name = 'history.structure_versions' then
        delete from history.structure_versions
        where source_run_id = p_source_run_id and city = p_city;
    else
        raise exception 'unsupported retention table: %', p_table_name;
    end if;
    get diagnostics deleted_rows = row_count;
    return deleted_rows;
end;
$$;

alter table staging.source_objects enable row level security;
alter table staging.structure_observations enable row level security;
alter table staging.structure_changes enable row level security;
alter table staging.promotion_batches enable row level security;
alter table staging.retention_policies enable row level security;
alter table history.structure_versions enable row level security;
alter table history.archive_manifests enable row level security;
alter table public.structure_conflicts enable row level security;
alter table public.structure_quality_issues enable row level security;
alter table public.structure_relationships enable row level security;
alter table public.structure_ai_suggestions enable row level security;

do $$
declare
    partition_number integer;
begin
    for partition_number in 0..7 loop
        execute format(
            'alter table history.structure_versions_p%s enable row level security',
            partition_number
        );
    end loop;
end
$$;

create index if not exists source_runs_source_object_idx
    on staging.source_runs (source_object_id);
create index if not exists structure_observations_source_object_idx
    on staging.structure_observations (source_object_id);

revoke all on staging.source_objects, staging.structure_observations,
    staging.structure_changes, staging.promotion_batches,
    history.structure_versions, history.archive_manifests,
    public.structure_conflicts, public.structure_quality_issues,
    public.structure_relationships, public.structure_ai_suggestions
from anon, authenticated;

grant usage on schema staging, history, extensions to service_role;
grant select, insert, update, delete on staging.source_objects,
    staging.structure_observations, staging.structure_changes,
    staging.promotion_batches, history.structure_versions,
    history.archive_manifests, public.structure_conflicts,
    public.structure_quality_issues, public.structure_relationships,
    public.structure_ai_suggestions to service_role;
grant usage, select on all sequences in schema history, public to service_role;

revoke all on function staging.stage_structure_observations(jsonb) from public, anon, authenticated;
revoke all on function public.promote_structure_batch_v3(text, integer, text, jsonb) from public, anon, authenticated;
revoke all on function public.finalize_structure_refresh_v3(text, integer, jsonb, jsonb) from public, anon, authenticated;
revoke all on function public.get_structure_passport(text) from public, anon, authenticated;
revoke all on function staging.purge_verified_archives(text, text, text) from public, anon, authenticated;
grant execute on function staging.stage_structure_observations(jsonb) to service_role;
grant execute on function public.promote_structure_batch_v3(text, integer, text, jsonb) to service_role;
grant execute on function public.finalize_structure_refresh_v3(text, integer, jsonb, jsonb) to service_role;
grant execute on function public.get_structure_passport(text) to service_role;
grant execute on function staging.purge_verified_archives(text, text, text) to service_role;
