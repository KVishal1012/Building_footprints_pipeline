# Structure Intelligence Database Data Dictionary

This dictionary documents the core structure table. Domain-specific fields live in additive extension tables keyed by `StructureID`.

## Core Identity

| Field | Meaning |
| --- | --- |
| `StructureID` | Stable structure join key for the core table and all extensions. |
| `PlaceGEOID`, `City`, `State`, `StateFP`, `Country` | Place and jurisdiction identifiers. |
| `geom` | Native PostGIS structure footprint in EPSG:4326. GiST indexed in staging, canonical, and history tables. |
| `geometry_wkt` | Delivery-only representation. New database refreshes use it transiently and do not retain a duplicate canonical copy. |

## Audit And Freshness

| Field | Meaning |
| --- | --- |
| `created_at`, `updated_at`, `updated_by` | Record audit metadata. |
| `change_log` | Compact record-level event references retained for compatibility. Field values live in `staging.structure_changes.field_deltas`. |
| `data_refresh_timestamp` | Single timestamp shared across source run, raw staging, change log, canonical promotion, coverage registry, and release manifest. |
| `last_refreshed` | Date/time the record was refreshed in this pipeline. |
| `source_as_of` | Upstream source vintage represented by the record. |

## Provenance

| Field | Meaning |
| --- | --- |
| `LoadSource` | Pipeline load family used for the row. AI is not allowed here. |
| `RawDataSource` | Raw upstream source used as source of truth. AI is not allowed here. |
| `FootprintSource` | Footprint source selected for geometry. |
| `CoverageTier` | Consumer-facing coverage tier for the city/market. |
| `*Source`, `*Confidence`, `*Method` | Attribute-level provenance, confidence, and method fields. |
| `StructureTypeSource` | Data source for `StructureType`. |
| `NumStoriesSource` | Data source for `NumStories`. |
| `NumUnitsSource` | Data source for `NumUnits`. |
| `OccupantCountSource` | Data source for `OccupantCount`. |

## Core Attributes

| Field | Meaning |
| --- | --- |
| `StructureType` | Canonical structure taxonomy value. |
| `NumUnits`, `NumStories` | Unit and story counts where available or derived. |
| `FootprintArea_m2`, `FootprintArea_sqft` | Computed footprint area. |
| `OccupantCount` | Occupant estimate with method and source fields. |

## AI Suggestions

AI suggestions live in `public.structure_ai_suggestions`, not in the canonical
attribute columns or canonical provenance fields.

| Field | Meaning |
| --- | --- |
| `PredictedStructureType`, `PredictedNumUnits`, `PredictedNumStories`, `PredictedOccupantCount` | Suggest-only AI predictions. |
| `PredictionKind`, `PredictionModelName`, `PredictionModelVersion` | Model provenance. |
| `PredictionConfidence`, `PredictionFeaturesUsed` | Prediction confidence and feature lineage. |
| `AIDisclosureLevel`, `PredictionSuppressionReason` | Consumer disclosure and suppression reason. |

## Structure Passport

`public.get_structure_passport(StructureID)` returns the current authoritative
profile, field provenance, freshness, geometry history, source conflicts, compact
change timeline, separate AI suggestions, QA warnings, and parcel/ward/hazard/
infrastructure relationships. See [Structure Passport](structure_passport.md).
