# Manhattan Structure Intelligence Demo Package

This package demonstrates **Structure Intelligence Database**: an audit-ready structure dataset where every core attribute includes source, confidence, freshness, and QA status.

## Data Promise

Audit-ready building attributes for risk models, planning workflows, and emergency intelligence, with source, confidence, and refresh trail for every field.

## Package Contents

- `sample_structures.csv`: canonical `public.structures`-ready sample rows.
- `provenance_snapshot.csv`: source and confidence fields for core attributes.
- `coverage_gap_registry.csv`: city-level completeness and freshness metrics.
- `release_manifest.json`: release, QA, delivery, and known-gap metadata.
- `one_page_brief.md`: concise implementation brief.

## Release Status

- Release gate status: `passed`
- Release gate blockers: `0`
- Row count: `2`
- Data refresh timestamp: `2026-06-06T12:00:00+00:00`
- Source vintage: `2026-Q2`

## Sample Structure Rows

| StructureID | StructureType | NumStories | NumUnits | OccupantCount | CoverageTier |
| --- | --- | --- | --- | --- | --- |
| nyc_pluto_mn_000001 | residential | 12 | 24 | 58 | Tier 1 |
| nyc_pluto_mn_000002 | commercial | 22 | 4 | 180 | Tier 1 |

## Provenance Snapshot

| StructureID | StructureTypeSource | NumStoriesSource | NumUnitsSource | OccupantCountSource |
| --- | --- | --- | --- | --- |
| nyc_pluto_mn_000001 | nyc_pluto_land_use | nyc_pluto_num_floors | nyc_pluto_units_total | nyc_pluto_occupancy |
| nyc_pluto_mn_000002 | nyc_pluto_land_use | nyc_pluto_num_floors | nyc_pluto_units_total | nyc_pluto_occupancy |

## Coverage And Completeness

| City | State | CoverageTier | row_count | structure_type_completeness | num_stories_completeness | num_units_completeness | occupant_count_completeness |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Manhattan | New York | Tier 1 | 2 | 1.0 | 1.0 | 1.0 | 1.0 |

## Before And After

| Raw footprint data | Structure Intelligence Database |
| --- | --- |
| Geometry only or thin attributes | Geometry plus type, stories, units, occupants |
| Source often hidden or dataset-level only | Attribute-level source and confidence |
| Staleness unclear | `data_refresh_timestamp`, `last_refreshed`, `source_as_of` |
| Hard to defend in risk/compliance reviews | Release manifest and QA gates |

## Delivery Options

- Supabase REST/PostgREST API
- SQL Server sync for enterprise deployments
- PostGIS/WKT table
- CSV, Parquet, and GeoJSON exports

## Known Gaps

- This is a small Manhattan proof package, not full production borough coverage.
- A production deployment should acquire current authoritative source rows for the requested city or AOI.
- AI remains suggest-only and is not used as source of truth.
