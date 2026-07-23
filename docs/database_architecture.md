# Database Architecture

Structure Intelligence Database is Supabase/Postgres-first. SQL Server remains available as an optional enterprise delivery layer for deployments that require it, but it is not the source of truth.

```text
Upstream Sources
PLUTO, Overture, NSI, Assessors, Parcels
        |
        v
Python Ingestion + QA Service
Railway / Fly.io / scheduled job
        |
        +--> Supabase: staging.raw_structures
        |       Raw source drops, source snapshots, provenance
        |
        +--> Change Detector
        |       Delta detection, refresh metadata, audit log
        |
        +--> QA / Provenance Gates
        |       Required fields, geometry, duplicate IDs, coverage tier, source lineage
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
| `staging.raw_structures` | Raw source drops before QA normalization. |
| `staging.change_log` | Delta logic output: inserts, updates, deletes, changed fields, and before/after payloads. |
| `staging.promotion_failures` | Rows blocked by QA/provenance gates before canonical promotion. |
| `staging.promotion_candidates` | QA-approved rows held until atomic refresh finalization. |
| `public.structures` | Canonical approved structure database exposed through Supabase REST/PostgREST. |
| `public.coverage_registry` | Coverage tier and completeness metrics by city/state. |
| `public.release_manifest` | Versioned release metadata and delivery package snapshots. |

## Promotion Rules

Rows may be promoted from staging to `public.structures` only after these gates pass:

- Required source/provenance fields are present.
- Attribute datasource fields are present for structure type, stories, units, and occupant count.
- `StructureID` is unique.
- Geometry is valid and non-empty.
- `CoverageTier` is assigned.
- AI values remain in prediction fields and never become `LoadSource` or `RawDataSource`.
- Audit and freshness fields are non-empty.
- `data_refresh_timestamp` is present on source run, staged rows, change-log rows, promoted canonical rows, coverage registry, and release manifest.
- Change detector has recorded the delta or confirmed no material change.

## Refresh Interfaces

The refresh layer exposes four Python interfaces:

| Function | Purpose |
| --- | --- |
| `run_source_refresh(source_name, city, state, config)` | Creates a source run and stages raw rows. |
| `detect_structure_changes(source_run_id, config)` | Compares staged rows against canonical rows and records deltas. |
| `promote_valid_changes(source_run_id, config)` | Runs QA gates and upserts valid rows into canonical structures. |
| `run_refresh_cycle(source_name, city, state, config)` | Runs staging, detection, promotion, coverage, and release metadata. |

The local implementation uses an in-memory store for dry-runs and tests. Production
runs use the Supabase-backed store through PostgREST with the service role key read
from `SUPABASE_SERVICE_ROLE_KEY`. Writes are bounded, reads are paginated, transient
requests retry with backoff, and approved candidates are finalized in one transaction.

## Delivery Positioning

Supabase is the canonical product database and primary API surface. SQL Server sync is a downstream delivery option for enterprise deployments. Bulk exports remain useful for analytics teams and distribution packaging.
