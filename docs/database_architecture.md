# Database Architecture

Structure Intelligence Database is Supabase/Postgres-first. SQL Server remains available as an optional enterprise delivery layer for deployments that require it, but it is not the source of truth.

```text
Upstream Sources
PLUTO, Overture, NSI, Assessors, Parcels
        |
        v
Private Object Storage
Immutable source files + SHA-256
        |
        v
Python Ingestion + QA Service
Railway / Fly.io / scheduled job
        |
        +--> staging.source_objects
        |       Source URI, checksum, byte size, verification state
        |
        +--> staging.structure_observations
        |       Normalized fields + native PostGIS geometry
        |
        +--> Change Detector
        |       Compact field deltas and record checksums
        |
        +--> QA / Provenance Gates
        |       Required fields, geometry, duplicate IDs, coverage tier, source lineage
        |
        +--> Bounded Transactional Promotion
        |       Idempotent batches + partitioned version history
        |
        +--> Supabase: public.structures
                Canonical structure database and source of truth
                    |
        +-----------+-----------+
        v           v           v
 Supabase API   SQL Server    Bulk Export
 REST/PostgREST enterprise    CSV / Parquet /
               sync           GeoJSON / WKT
```

## Table Contract

| Table | Role |
| --- | --- |
| `staging.source_runs` | One row per upstream ingestion run, including source vintage, cadence, row count, and status. |
| `staging.source_objects` | Checksummed references to immutable files in the private `structure-source-archives` bucket. |
| `staging.structure_observations` | Normalized source fields and native EPSG:4326 PostGIS geometry. Raw file content is not duplicated here. |
| `staging.structure_changes` | Inserts, updates, delete candidates, checksums, and changed field values only. |
| `staging.promotion_failures` | Rows blocked by QA/provenance gates before canonical promotion. |
| `staging.promotion_batches` | Idempotency and completion ledger for bounded promotion transactions. |
| `public.structures` | Canonical approved structure database exposed through Supabase REST/PostgREST. |
| `public.coverage_registry` | Coverage tier and completeness metrics by city/state. |
| `public.release_manifest` | Versioned release metadata and delivery package snapshots. |
| `history.structure_versions` | Hash-partitioned attribute and geometry history by city and source run. |
| `public.structure_conflicts` | Conflicting source values and resolution state. |
| `public.structure_quality_issues` | Open, resolved, or waived QA warnings. |
| `public.structure_relationships` | Parcel, ward, hazard, and infrastructure links. |
| `public.structure_ai_suggestions` | Suggest-only model output, separate from canonical attributes. |

## Promotion Rules

Rows may be promoted from staging to `public.structures` only after these gates pass:

- Required source/provenance fields are present.
- Attribute datasource fields are present for structure type, stories, units, and occupant count.
- `StructureID` is unique.
- Geometry is valid and non-empty.
- `CoverageTier` is assigned.
- AI values remain in prediction fields and never become `LoadSource` or `RawDataSource`.
- Audit and freshness fields are non-empty.
- `data_refresh_timestamp` is present on source run, observations, changes, canonical rows, coverage registry, and release manifest.
- The source object exists in private storage and its streamed SHA-256 matches the local acquisition file.
- Change detector has recorded the delta or confirmed no material change.
- Every promotion batch is complete and the promoted count matches the release manifest.

## Refresh Interfaces

The refresh layer exposes four Python interfaces:

| Function | Purpose |
| --- | --- |
| `run_source_refresh(source_name, city, state, config)` | Verifies the source object, creates a source run, and stages normalized observations. |
| `detect_structure_changes(source_run_id, config)` | Compares staged rows against canonical rows and records deltas. |
| `promote_valid_changes(source_run_id, config)` | Runs QA gates and upserts valid rows into canonical structures. |
| `run_refresh_cycle(source_name, city, state, config)` | Runs staging, detection, promotion, coverage, and release metadata. |

The local implementation uses an in-memory store for dry-runs and tests. Production
runs use the Supabase-backed store through PostgREST with the service role key read
from `SUPABASE_SERVICE_ROLE_KEY`. Writes are bounded, reads are paginated, transient
requests retry with backoff, and each bounded canonical batch is promoted in its own
transaction. Release metadata is finalized only after the batch ledger reconciles.

## Retention

Retention is archive-first. `staging.retention_policies` defines default lifetimes,
and `staging.purge_verified_archives(...)` refuses deletion until a matching,
checksummed row exists in `history.archive_manifests`. Canonical rows are never
hard-deleted by a normal refresh; missing records become `delete_candidate` events.

## Delivery Positioning

Supabase is the canonical product database and primary API surface. SQL Server sync is a downstream delivery option for enterprise deployments. Bulk exports remain useful for analytics teams and distribution packaging.
