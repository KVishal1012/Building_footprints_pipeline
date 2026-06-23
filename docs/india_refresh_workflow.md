# India Refresh Workflow

The India branch starts with Chennai and expands across Tamil Nadu city by city. Chennai is the active proof market. Coimbatore, Madurai, Tiruchirappalli, Salem, and Tiruppur are registered as planned expansion targets.

## Chennai Runner

Run the local Chennai refresh workflow:

```bash
python scripts/run_chennai_refresh.py \
  --source-file examples/india_chennai_refresh_source.csv \
  --data-refresh-timestamp 2026-06-23T12:00:00+00:00 \
  --include-registries
```

The runner uses the same refresh contract as the canonical Supabase/Postgres workflow:

- stages prepared rows into raw refresh records
- detects inserts, updates, unchanged rows, and delete candidates
- runs geometry, provenance, freshness, and datasource QA gates
- promotes valid rows into the canonical refresh store
- creates release metadata with gate status and blockers

Use `--dry-run` to compute staging, changes, and QA without mutating the selected store. Use `--store supabase` only when `--supabase-url` is provided and the configured service role environment variable is available locally.

## City Registry

The Tamil Nadu registry is defined in `structures_pipeline/india.py`. It records:

- city and state names
- coverage tier
- active or planned status
- default source name
- default prepared source file when available
- known gap text
- expansion order

Chennai has a committed prepared source fixture. Planned expansion cities intentionally have no fixture until their source mapping is prepared.

## Source Strategy

Overture and OSM are treated as footprint and fallback sources. Municipal, planning, tax, ward, parcel, disaster, or state datasets become authoritative only after they are acquired, labeled, and mapped into canonical fields.

Proxy attributes are allowed only when the relevant datasource fields make that treatment explicit. AI remains suggest-only and must not appear as `RawDataSource`, `LoadSource`, `FootprintSource`, or any core attribute source.
