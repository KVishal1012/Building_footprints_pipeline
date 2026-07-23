-- Chennai production refresh hardening.
-- Run migrations/001_supabase_refresh_schema.sql first.

alter table staging.source_runs
    add column if not exists city text,
    add column if not exists state text;

update staging.source_runs
set city = coalesce(city, metadata ->> 'city'),
    state = coalesce(state, metadata ->> 'state')
where city is null or state is null;

alter table staging.raw_structures
    drop constraint if exists raw_structures_pkey;
alter table staging.raw_structures
    add primary key (source_run_id, raw_record_id);

create table if not exists staging.promotion_candidates (
    source_run_id text not null references staging.source_runs(source_run_id) on delete cascade,
    structure_id text not null,
    canonical_payload jsonb not null,
    staged_at timestamptz not null default now(),
    primary key (source_run_id, structure_id)
);

alter table public.structures
    add column if not exists source_authority text,
    add column if not exists source_family text,
    add column if not exists provenance_tier text,
    add column if not exists source_run_id text;

create index if not exists idx_source_runs_city_state
    on staging.source_runs(city, state);
create index if not exists idx_raw_structures_run
    on staging.raw_structures(source_run_id);
create index if not exists idx_change_log_run_type
    on staging.change_log(source_run_id, change_type);
create index if not exists idx_promotion_failures_run
    on staging.promotion_failures(source_run_id);
create index if not exists idx_structures_city_state_source
    on public.structures(city, state, raw_data_source);
create index if not exists idx_structures_source_run
    on public.structures(source_run_id);

alter table public.structures
    drop constraint if exists structures_positive_area,
    drop constraint if exists structures_type_source_required,
    drop constraint if exists structures_stories_source_required,
    drop constraint if exists structures_units_source_required,
    drop constraint if exists structures_occupants_source_required,
    drop constraint if exists structures_provenance_required,
    drop constraint if exists structures_ai_not_authoritative,
    drop constraint if exists structures_change_log_array;

alter table public.structures
    add constraint structures_positive_area
        check (footprint_area_m2 is not null and footprint_area_m2 > 0),
    add constraint structures_type_source_required
        check (structure_type is null or nullif(btrim(structure_type_source), '') is not null),
    add constraint structures_stories_source_required
        check (num_stories is null or nullif(btrim(num_stories_source), '') is not null),
    add constraint structures_units_source_required
        check (num_units is null or nullif(btrim(num_units_source), '') is not null),
    add constraint structures_occupants_source_required
        check (occupant_count is null or nullif(btrim(occupant_count_source), '') is not null),
    add constraint structures_provenance_required
        check (
            nullif(btrim(source_authority), '') is not null
            and nullif(btrim(source_family), '') is not null
            and nullif(btrim(provenance_tier), '') is not null
            and nullif(btrim(source_run_id), '') is not null
        ),
    add constraint structures_ai_not_authoritative
        check (
            lower(concat_ws(' ', load_source, raw_data_source, footprint_source,
                structure_type_source, num_stories_source, num_units_source,
                occupant_count_source))
            !~ '(^|[^a-z])(ai|ml_inference|model_prediction|prediction)([^a-z]|$)'
        ),
    add constraint structures_change_log_array
        check (jsonb_typeof(change_log) = 'array');

alter table staging.source_runs enable row level security;
alter table staging.raw_structures enable row level security;
alter table staging.change_log enable row level security;
alter table staging.promotion_failures enable row level security;
alter table staging.promotion_candidates enable row level security;
alter table public.structures enable row level security;
alter table public.coverage_registry enable row level security;
alter table public.release_manifest enable row level security;

revoke all on schema staging from public, anon, authenticated;
revoke all on all tables in schema staging from public, anon, authenticated;
revoke all on public.structures, public.coverage_registry, public.release_manifest
    from anon, authenticated;

grant usage on schema staging to service_role;
grant all on all tables in schema staging to service_role;
grant all on public.structures, public.coverage_registry, public.release_manifest
    to service_role;

create or replace function public.finalize_structure_refresh(
    p_source_run_id text,
    p_coverage_rows jsonb,
    p_release_manifest jsonb
)
returns void
language plpgsql
security invoker
set search_path = pg_catalog
as $$
declare
    request_role text;
begin
    request_role := coalesce(
        (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role'),
        ''
    );
    if request_role <> 'service_role' then
        raise exception 'service_role is required'
            using errcode = '42501';
    end if;

    if not exists (
        select 1
        from staging.source_runs
        where source_run_id = p_source_run_id
    ) then
        raise exception 'unknown source_run_id: %', p_source_run_id;
    end if;

    if exists (
        select 1
        from staging.promotion_failures
        where source_run_id = p_source_run_id
    ) then
        raise exception 'promotion failures exist for source_run_id: %', p_source_run_id;
    end if;

    insert into public.structures
    select candidate.*
    from staging.promotion_candidates staged
    cross join lateral jsonb_populate_record(
        null::public.structures,
        staged.canonical_payload
    ) as candidate
    where staged.source_run_id = p_source_run_id
    on conflict (structure_id) do update set
        city = excluded.city,
        state = excluded.state,
        country = excluded.country,
        coverage_tier = excluded.coverage_tier,
        geometry_wkt = excluded.geometry_wkt,
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
        ai_suggestions = excluded.ai_suggestions,
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

    insert into public.coverage_registry
    select coverage.*
    from jsonb_array_elements(coalesce(p_coverage_rows, '[]'::jsonb)) element
    cross join lateral jsonb_populate_record(
        null::public.coverage_registry,
        element
    ) as coverage
    on conflict (city, state) do update set
        coverage_tier = excluded.coverage_tier,
        row_count = excluded.row_count,
        completeness = excluded.completeness,
        source_summary = excluded.source_summary,
        data_refresh_timestamp = excluded.data_refresh_timestamp,
        last_refreshed = excluded.last_refreshed,
        source_as_of = excluded.source_as_of;

    insert into public.release_manifest
    select release_row.*
    from jsonb_populate_record(
        null::public.release_manifest,
        p_release_manifest
    ) as release_row
    on conflict (release_id) do update set
        generated_at = excluded.generated_at,
        schema_version = excluded.schema_version,
        row_count = excluded.row_count,
        manifest = excluded.manifest;

    update staging.source_runs
    set status = 'completed',
        completed_at = now()
    where source_run_id = p_source_run_id;

    delete from staging.promotion_candidates
    where source_run_id = p_source_run_id;
end;
$$;

revoke all on function public.finalize_structure_refresh(text, jsonb, jsonb)
    from public, anon, authenticated;
grant execute on function public.finalize_structure_refresh(text, jsonb, jsonb)
    to service_role;
