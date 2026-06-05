# Database Architecture

Structure Intelligence Database is Supabase/Postgres-first. SQL Server remains available as an optional enterprise delivery layer for buyers who require it, but it is not the source of truth.

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
| `public.structures` | Canonical approved structure database exposed through Supabase REST/PostgREST. |
| `public.coverage_registry` | Coverage tier and completeness metrics by city/state. |
| `public.release_manifest` | Versioned release metadata and delivery package snapshots. |

## Promotion Rules

Rows may be promoted from staging to `public.structures` only after these gates pass:

- Required source/provenance fields are present.
- `StructureID` is unique.
- Geometry is valid and non-empty.
- `CoverageTier` is assigned.
- AI values remain in prediction fields and never become `LoadSource` or `RawDataSource`.
- Audit and freshness fields are non-empty.
- Change detector has recorded the delta or confirmed no material change.

## Delivery Positioning

Supabase is the canonical product database and primary API surface. SQL Server sync is a downstream delivery option for enterprise buyers. Bulk exports remain useful for analytics teams and marketplace packaging.
