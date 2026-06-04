# Structure Intelligence Database Product Map

## Product Direction

The product is a structure intelligence database for teams that need reliable building and structure data across cities, states, hazards, assets, and operating regions. The pipeline, SQL Server modules, and AI models are supporting systems; the end product is the database that users query, export, and trust.

The database should answer four questions for every attribute:

- What is the value?
- Where did it come from?
- How confident is it?
- Was it authoritative, derived, estimated, or AI-suggested?

## Core Database

Every structure record should preserve a stable ID, geometry, location context, source lineage, physical attributes, occupancy attributes, and confidence/provenance fields.

Core fields:

- `StructureID`
- `geometry` or exported `geometry_wkt`
- city, state, county, census identifiers
- parcel/address links where available
- footprint area
- structure type
- units
- stories
- height
- occupant count
- baseline/linkage fields
- source, method, confidence, and model provenance

The core table is designed to support broad users without forcing each team to rebuild building data from raw geospatial sources.

## Source Of Truth Model

SQL Server is a load/export mechanism, not a raw authority by itself. The final table must distinguish:

- `LoadSource`: how the data entered the system, such as `sql_server`
- `RawDataSource`: the actual upstream authority, such as `nyc_pluto`, `nyc_building_footprints`, `assessor`, `nsi`, `overture`, or `osm`
- per-attribute source fields, such as `StructureTypeSource`, `NumUnitsSource`, `NumStoriesSource`, and `OccupantCountSource`
- confidence fields for every major inferred or sourced attribute

Authoritative raw sources should be prioritized over public enrichment data. Public data and AI should reduce gaps, but should not silently replace authoritative values.

## Use-Case Extensions

Urban planning:

- zoning
- land use
- parcel ID
- year built
- assessed value
- residential/commercial/mixed-use classification

Flood monitoring:

- flood zone
- elevation
- nearest water body
- flood exposure category
- basement or ground-floor indicators where available

Oil and gas:

- distance to wells, pipelines, tanks, terminals, and facilities
- asset buffer relationships
- critical infrastructure tags
- exposure class

Weather monitoring:

- wind, hail, tornado, and storm exposure zones
- roof/height class where available
- severe-weather risk categories

Emergency response:

- estimated occupants
- critical facility flag
- school, hospital, public, and shelter indicators
- access/address context

## AI Role

AI models support the database by filling gaps, scoring confidence, and flagging anomalies. AI does not define the source of truth.

V1 AI behavior:

- suggest-only predictions
- no overwrite of authoritative fields
- prediction provenance stored separately
- confidence threshold required before emitting predictions

AI fields:

- `PredictedStructureType`
- `PredictedNumUnits`
- `PredictedNumStories`
- `PredictedOccupantCount`
- `PredictionKind`
- `PredictionModelName`
- `PredictionModelVersion`
- `PredictionConfidence`
- `PredictionFeaturesUsed`

Future AI phases can add model-assisted source matching, anomaly detection, and deep learning for imagery or geometry, but they must use the same provenance contract.

## Product Phases

Phase 1: Trusted Core Database

- source-of-truth schema
- SQL Server table-only export
- raw source labels
- baseline buffering and linkage
- dataframe preview for operators

Phase 2: Attribute Coverage

- authoritative source mapping by city/region
- parcel and assessor integrations
- NSI/ACS enrichment
- attribute completeness metrics

Phase 3: AI Assistance

- suggest-only gap filling
- model provenance
- low-confidence suppression
- no authoritative overwrite

Phase 4: Domain Extensions

- flood exposure tables
- oil and gas asset proximity tables
- weather risk overlays
- planning/zoning extension tables

Phase 5: Database Productization

- release/version metadata
- repeatable refresh workflow
- consumer-facing documentation
- data quality dashboard
- stable API/query views
