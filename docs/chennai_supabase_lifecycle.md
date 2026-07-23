# Chennai Supabase Refresh Lifecycle

This workflow promotes only an accepted Chennai canonical snapshot. Raw acquisition
files, generated GeoParquet, reports, credentials, and machine-local settings stay
outside Git.

## Source Contract

The first production snapshot uses:

- OpenStreetMap building footprints and explicit building tags
- Greater Chennai Corporation ward polygons as the accepted AOI
- the acquisition `source_manifest.json` as the feature-count and vintage receipt

OSM is an open community source, not a municipal authority. Unknown stories, units,
occupant counts, and unrecognized structure types remain `NULL`.

## Local Settings

Copy the template once and edit the local module:

```bash
cp india_local_inputs.example.py india_local_inputs.py
```

The ignored `india_local_inputs.py` contains source paths, output paths, the Supabase
project URL, and run mode. The service role key is read only from the environment
named by `SUPABASE_SERVICE_ROLE_ENV`.

## Acceptance Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_chennai_real_source.py
```

The command blocks when:

- manifest counts do not match source files
- source IDs are missing or duplicated
- geometry is empty, invalid, or not polygonal
- source counts do not reconcile
- a populated core attribute lacks its datasource
- ward assignments remain ambiguous
- canonical columns differ from the approved contract

Exact duplicate footprints are quarantined in the report. Features outside the GCC
AOI are excluded and counted. Neither condition is hidden.

## Database Setup

Run these files in order in the dedicated Chennai Supabase project:

```text
migrations/001_supabase_refresh_schema.sql
migrations/002_chennai_refresh_lifecycle.sql
```

In **Project Settings > Data API**, expose `public` and `staging`. The migration
explicitly grants the backend `service_role`, revokes `anon` and `authenticated`,
and enables RLS on all lifecycle tables. Do not place the service role key in a
browser or committed file.

The second migration adds:

- composite raw snapshot identity: `(source_run_id, raw_record_id)`
- provenance and source-run columns on `public.structures`
- QA constraints for source-only attributes and AI separation
- bounded-promotion staging in `staging.promotion_candidates`
- `public.finalize_structure_refresh(...)` as a service-role-only,
  `SECURITY INVOKER` transaction
- city/source indexes and RLS/grant hardening

## Dry Run

Keep these settings:

```python
SUPABASE_STORE = "in_memory"
DRY_RUN = True
PROMOTE_TO_CANONICAL = True
```

Then run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_chennai_supabase_refresh.py
```

The dry run executes staging, change detection, QA, coverage, and release gates
without any remote mutation.

## Production Promotion

Set:

```python
SUPABASE_URL = "https://PROJECT_REF.supabase.co"
SUPABASE_STORE = "supabase"
DRY_RUN = False
PROMOTE_TO_CANONICAL = True
```

Export the credential in the process environment, then run the same lifecycle
command. The runner:

1. verifies all required PostgREST tables
2. stages source-run and raw rows in bounded batches
3. reads canonical rows with pagination and Chennai/source filters
4. records inserts, updates, unchanged rows, and delete candidates
5. writes failed rows to `staging.promotion_failures`
6. stages approved candidates
7. atomically promotes candidates and updates coverage/release metadata

Delete candidates never hard-delete structures in this lifecycle.

## Required Receipt

Do not call a refresh complete unless the lifecycle report records:

- `status = passed`
- the deterministic `source_run_id`
- source SHA-256 and source vintage
- input, change, promoted, and failed counts
- `failed_count = 0`
- `release_gate_status = passed`
- no release gate blockers
