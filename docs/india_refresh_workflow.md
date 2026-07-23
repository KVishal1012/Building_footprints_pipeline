# India Refresh Workflow

The India branch starts with Chennai and expands across Tamil Nadu city by city. Chennai is the active proof market. Coimbatore, Madurai, Tiruchirappalli, Salem, and Tiruppur are registered as planned expansion targets.

## Chennai Real-Source Runner

Configure ignored machine-local inputs:

```bash
cp india_local_inputs.example.py india_local_inputs.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_chennai_real_source.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_chennai_supabase_refresh.py
```

The real-source runner reads the acquired OSM footprint file, GCC wards, and source
manifest. It creates a local accepted canonical snapshot before the Supabase lifecycle
can run. See `docs/chennai_supabase_lifecycle.md` for database setup and promotion.

The committed `examples/india_chennai_refresh_source.csv` and
`scripts/run_chennai_refresh.py` remain small smoke-test fixtures. They are not the
production Chennai source.

The lifecycle:

- stages prepared rows into raw refresh records
- detects inserts, updates, unchanged rows, and delete candidates
- runs geometry, provenance, freshness, and datasource QA gates
- promotes valid rows into the canonical refresh store
- creates release metadata with gate status and blockers

Dry-run and production settings are supplied through `india_local_inputs.py`, not
repeated as CLI inputs. Supabase credentials remain environment-only.

## City Registry

The Tamil Nadu registry is defined in `structures_pipeline/india.py`. It records:

- city and state names
- coverage tier
- active or planned status
- default source name
- default prepared source file when available
- known gap text
- expansion order

Chennai has a committed smoke-test fixture and a local real-source contract. Planned
expansion cities intentionally have no source mapping until their acquisition receipts,
AOIs, and provenance treatment are prepared.

## Source Strategy

OSM is treated as an open-community footprint and tag source. Municipal, planning,
tax, ward, parcel, disaster, or state datasets become authoritative only after they
are acquired, labeled, and mapped into canonical fields.

Unknown attributes stay null. AI remains suggest-only and must not appear as
`RawDataSource`, `LoadSource`, `FootprintSource`, or any core attribute source.
