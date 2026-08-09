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
migrations/003_compact_structure_foundation_and_passports.sql
```

In **Project Settings > Data API**, expose `public` and `staging`. The migration
explicitly grants the backend `service_role`, revokes `anon` and `authenticated`,
and enables RLS on all lifecycle tables. Do not place the service role key in a
browser or committed file.

The third migration supersedes the JSON-heavy staging path for new runs and adds:

- private object-storage archive registration and checksum verification
- normalized `staging.structure_observations` with native PostGIS geometry
- compact field-level deltas in `staging.structure_changes`
- GiST indexes for spatial intersection and proximity queries
- bounded, idempotent `public.promote_structure_batch_v3(...)` transactions
- hash-partitioned geometry and attribute history
- archive-gated retention policies
- Structure Passport conflicts, QA, AI, and relationship tables
- `public.get_structure_passport(...)`

Create the private `structure-source-archives` bucket through the Supabase Storage
API or dashboard. The SQL migration intentionally does not modify the internal
`storage` schema.

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
REQUIRE_SOURCE_ARCHIVE = True
SOURCE_OBJECT_URI = "supabase://structure-source-archives/chennai/osm/buildings.geojson"
```

Upload the exact acquisition file to the private bucket before running. Files larger
than 6 MB should use Supabase resumable upload; the refresh runner does not silently
substitute a local path. Export the credential in the process environment, then run
the same lifecycle command. The runner:

1. verifies all required PostgREST tables
2. streams the private object and verifies its SHA-256
3. stages source-run and normalized observations in bounded batches
4. reads canonical rows with pagination and Chennai/source filters
5. records compact inserts, updates, unchanged rows, and delete candidates
6. writes failed row references to `staging.promotion_failures`
7. promotes approved rows in bounded transactions
8. reconciles the batch ledger before coverage/release metadata is committed

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
- source object status is verified
- completed promotion batch rows equal the manifest promoted count
