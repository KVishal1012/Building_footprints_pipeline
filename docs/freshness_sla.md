# Freshness And Refresh SLA

Every release should publish record freshness and upstream source vintage. The default contract is conservative until automated source-specific jobs are scheduled.

| Source Family | Target Cadence | Consumer Signal |
| --- | --- | --- |
| City assessor or PLUTO-style authoritative sources | Quarterly, aligned to upstream releases. | `last_refreshed`, `source_as_of`, `change_log`. |
| NSI / FEMA-style inventory | Annual or when upstream publishes a new release. | `source_as_of` and reload notes in release manifest. |
| Overture Maps | Monthly. | Geometry and attribute delta notes in release manifest. |
| OSM | Weekly for configured markets. | Changeset-derived refresh timestamp where enabled. |
| AI predictions | On demand or after source refresh. | `PredictionModelVersion`, `PredictionFeaturesUsed`, `PredictionConfidence`. |

Release packages should include:

- `release_manifest.json` with release id, generated time, delivery paths, and config snapshot.
- Coverage gap registry with completeness percentages.
- Source vintage metadata in `source_as_of`.
- Per-record `last_refreshed`.
- One explicit `data_refresh_timestamp` shared across source run, raw staging, change-log, canonical, coverage, and release manifest records.

## First Production Rollout

The first refresh market is Manhattan, New York, using NYC PLUTO/assessor-style authoritative rows, Overture footprints, and NSI enrichment. SQL Server remains a downstream sync target only when an enterprise buyer needs it.

## Operator Commands

Dry-run a prepared Manhattan source file without promoting rows:

```bash
python scripts/run_refresh_pipeline.py \
  --source-file data/prepared/manhattan_structures.parquet \
  --source-name nyc_pluto \
  --source-family assessor \
  --source-as-of 2026-Q2 \
  --data-refresh-timestamp 2026-06-06T12:00:00+00:00 \
  --refresh-cadence quarterly \
  --city Manhattan \
  --state "New York" \
  --dry-run
```

Run a production refresh cycle from the prepared source file:

```bash
python scripts/run_refresh_pipeline.py \
  --source-file data/prepared/manhattan_structures.parquet \
  --source-name nyc_pluto \
  --source-family assessor \
  --source-as-of 2026-Q2 \
  --data-refresh-timestamp 2026-06-06T12:00:00+00:00 \
  --refresh-cadence quarterly \
  --city Manhattan \
  --state "New York"
```

Coverage registry and release manifest rows are updated by the refresh cycle after promotion succeeds. To sync the canonical output to SQL Server for an enterprise buyer, use the existing SQL Server runner:

```bash
python scripts/run_sql_server_pipeline.py
```
