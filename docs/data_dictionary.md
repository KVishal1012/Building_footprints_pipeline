# Structure Intelligence Database Data Dictionary

This dictionary documents the core structure table. Domain-specific fields live in additive extension tables keyed by `StructureID`.

## Core Identity

| Field | Meaning |
| --- | --- |
| `StructureID` | Stable structure join key for the core table and all extensions. |
| `PlaceGEOID`, `City`, `State`, `StateFP`, `Country` | Place and jurisdiction identifiers. |
| `geometry` / `geometry_wkt` | Structure footprint geometry in EPSG:4326 or export-specific WKT. |

## Audit And Freshness

| Field | Meaning |
| --- | --- |
| `created_at`, `updated_at`, `updated_by` | Record audit metadata. |
| `change_log` | JSON-compatible change trail for release and refresh workflows. |
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

| Field | Meaning |
| --- | --- |
| `PredictedStructureType`, `PredictedNumUnits`, `PredictedNumStories`, `PredictedOccupantCount` | Suggest-only AI predictions. |
| `PredictionKind`, `PredictionModelName`, `PredictionModelVersion` | Model provenance. |
| `PredictionConfidence`, `PredictionFeaturesUsed` | Prediction confidence and feature lineage. |
| `AIDisclosureLevel`, `PredictionSuppressionReason` | Consumer disclosure and suppression reason. |
