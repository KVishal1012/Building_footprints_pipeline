# Chennai Structure Intelligence Demo Package

This package demonstrates the Chennai-first India version of **Structure Intelligence Database**: an audit-ready structure dataset where every core attribute includes source, confidence, freshness, and QA status.

## Data Promise

Audit-ready structure data for Chennai, with source, confidence, freshness, and QA status for every field.

## Package Contents

- `sample_structures.csv`: canonical `public.structures`-ready Chennai sample rows.
- `provenance_snapshot.csv`: source and confidence fields for core attributes.
- `coverage_gap_registry.csv`: Chennai completeness, freshness, and known-gap metrics.
- `release_manifest.json`: release, QA, delivery, and Tamil Nadu expansion metadata.
- `one_page_brief.md`: concise implementation brief.

## Release Status

- Release gate status: `passed`
- Release gate blockers: `0`
- Row count: `3`
- Data refresh timestamp: `2026-06-20T12:00:00+00:00`
- Source vintage: `2026-Q2`

## Sample Structure Rows

| StructureID | StructureType | NumStories | NumUnits | OccupantCount | CoverageTier |
| --- | --- | --- | --- | --- | --- |
| india_chennai_000001 | residential | 4 | 8 | 32 | Tier 4 |
| india_chennai_000002 | commercial | 6 | 1 | 75 | Tier 4 |
| india_chennai_000003 | public | 3 | 1 | 220 | Tier 4 |

## Provenance Snapshot

| StructureID | StructureTypeSource | NumStoriesSource | NumUnitsSource | OccupantCountSource |
| --- | --- | --- | --- | --- |
| india_chennai_000001 | overture_maps_building_class | osm_building_levels | heuristic_proxy_residential_units | heuristic_proxy_units_x_household_size |
| india_chennai_000002 | osm_building_tag | heuristic_proxy_height_to_stories | heuristic_proxy_nonresidential_units | heuristic_proxy_commercial_occupancy_density |
| india_chennai_000003 | overture_maps_building_class | osm_building_levels | heuristic_proxy_public_facility_units | heuristic_proxy_public_facility_occupancy |

## Coverage And Completeness

| City | State | CoverageTier | row_count | structure_type_completeness | num_stories_completeness | num_units_completeness | occupant_count_completeness |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Chennai | Tamil Nadu | Tier 4 | 3 | 1.0 | 1.0 | 1.0 | 1.0 |

## Tamil Nadu Expansion Path

Chennai is the template package. The next city expansion targets are: Coimbatore, Madurai, Tiruchirappalli, Salem, Tiruppur.

## India Source Strategy

| Source type | Product treatment |
| --- | --- |
| Overture / OSM footprints | Footprint and fallback sources |
| Municipal, planning, tax, ward, parcel, disaster datasets | Authoritative only when acquired and labeled |
| Proxy attributes | Allowed only when clearly labeled as heuristic/proxy |
| AI predictions | Suggest-only; never source of truth |

## Delivery Options

- Supabase REST/PostgREST API
- SQL Server sync for enterprise deployments
- PostGIS/WKT table
- CSV, Parquet, and GeoJSON exports

## Known Gaps

- This is a small Chennai proof package, not full Tamil Nadu coverage.
- A production deployment should acquire current authoritative source rows for the requested city or area of interest.
- Proxy fields are intentionally labeled and should not be presented as authoritative.
