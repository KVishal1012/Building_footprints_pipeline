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
