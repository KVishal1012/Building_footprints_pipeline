# Structure Intelligence Database

Product Map - Revised Strategy  
Version 2.0 | June 2026

## Why This Revision

The original product map was architecturally sound. This revision addresses four gaps that would have created friction at the point of sale and at the point of production deployment:

| Original Gap | Addressed By |
| --- | --- |
| No data freshness or refresh cadence defined | Automated refresh pipeline added to Phase 2 |
| SQL Server-only delivery limits buyer base | Multi-format delivery layer promoted to Phase 2 |
| Coverage gaps in mid-tier cities unaddressed | Coverage tier model and gap registry added to Phase 2 |
| Competitive moat understated | Compliance and provenance GTM story formalized as core positioning |

## Product Direction

Structure Intelligence Database is a trusted, audit-ready building and structure data layer for teams that cannot afford to discover a data quality problem after a policy is written, a risk is underwritten, or a response plan is activated.

The database answers four questions for every attribute:

- What is the value?
- Where did it come from?
- How confident is it?
- Was it authoritative, derived, estimated, or AI-suggested?

The core differentiation:

Every competitor gives you a number. This database tells you how much to trust it, who said it, and when it was last verified. That provenance contract is the product.

## GTM Positioning

### The Problem We Solve

Insurers misprice risk because building attributes are wrong or unverifiable. Emergency managers deploy resources based on occupancy counts that are years out of date. Climate risk analysts overlay flood models on structure data they cannot audit. In all three cases, the root cause is not bad models. It is untrustworthy input data.

### Positioning Statement

For risk and intelligence teams who cannot trust their building data, Structure Intelligence Database is the only structure data layer that ships every attribute with its source, confidence score, and provenance classification, making it the first building dataset that is audit-ready by design. Unlike Regrid, Overture, or NSI, we do not just give you a number. We give you a traceable chain of custody for every field.

### Primary Buyer Personas

| Persona | Pain Point | Why They Pay |
| --- | --- | --- |
| Insurance Underwriter | Mispriced risk due to bad structure attributes | One avoided loss event can exceed the contract value |
| Climate Risk Analyst | Cannot document data lineage for ESG/regulatory reporting | Compliance mandate drives procurement |
| Emergency Manager | Occupancy counts are stale; critical facility flags missing | Life safety justifies budget |
| Proptech / RE Analytics | Rebuilding building data from raw sources is expensive | Developer time saved exceeds subscription cost |
| Municipal Planning Dept | No single source covering zoning, structure, and risk | Grant-funded or capital budget procurement |

### Competitive Landscape

| Competitor | What They Offer | What They Miss | Our Wedge |
| --- | --- | --- | --- |
| Regrid | Parcel and ownership data | Structure attributes are thin; no AI gap-filling | Richer structure schema and provenance |
| Overture Maps | Open building footprints | No confidence scoring; no source lineage per attribute | Attribute-level trust layer |
| NSI/FEMA | National structure inventory | Static, infrequent refresh, no API | Live refresh and multi-format delivery |
| CoreLogic | Rich property data | Black box; no model provenance | Transparent confidence and audit trail |
| Custom builds | Tailored to organization needs | Every team rebuilds from scratch | Shared trusted layer, no rebuild cost |

### Compliance Angle

Insurers and reinsurers are under growing regulatory pressure to document why underwriting decisions were made. Climate risk disclosures such as TCFD, SEC climate rules, and OSFI B-15 in Canada require firms to trace risk exposure to its data sources. A database that ships `PredictionConfidence`, `PredictionModelVersion`, and `PredictionFeaturesUsed` per attribute is compliance infrastructure, not just a data product. This is a faster procurement path than competing on coverage alone.

## Revised Product Roadmap

What changed from v1:

- Data freshness and multi-format delivery moved from Phase 5 to Phase 2 because buyers will ask about them before signing.
- Coverage tier model added to Phase 2 because coverage gaps discovered post-sale destroy trust.
- Compliance and audit positioning are now part of Phase 1 schema design rather than a late productization feature.

| Phase | Name | Timeline | Key Deliverables |
| --- | --- | --- | --- |
| 1 | Trusted Core Database | Months 1-2 | Schema, SQL Server and PostGIS export, source-of-truth model, provenance fields, audit trail design |
| 2 | Coverage + Delivery | Months 2-4 | Refresh pipeline, multi-format API, coverage tier model, gap registry, attribute completeness dashboard |
| 3 | AI Assistance | Months 4-6 | Suggest-only gap-filling, model provenance fields, confidence thresholding, no authoritative overwrite |
| 4 | Domain Extensions | Months 6-9 | Flood, oil and gas, weather, planning extension tables with vertical-specific attribute sets |
| 5 | Platform + Distribution | Months 9-12 | Versioned release workflow, consumer docs, data quality SLA dashboard, marketplace listing |

## Phase 1 - Trusted Core Database

The audit trail design must be baked into the schema at this stage, not retrofitted later.

Core schema fields:

- `StructureID`
- `geometry` / `geometry_wkt`
- city, state, county, census identifiers
- parcel and address links where available
- footprint area, structure type, units, stories, height, occupant count
- source, method, confidence, and model provenance per attribute
- `created_at`
- `updated_at`
- `updated_by`
- `change_log`

## Phase 2 - Coverage + Delivery

This phase is restructured because delivery format and data freshness are sales blockers. Buyers in insurance and climate risk will ask how they get the data and how stale it is before signing.

### Refresh Pipeline

- Automated ingestion jobs per upstream source, including NYC PLUTO, assessor feeds, NSI, and Overture.
- Change detection layer compares incoming records against current records and flags deltas.
- Refresh cadence metadata is tracked per source: daily, weekly, quarterly, or on-demand.
- Record-level `last_refreshed` and `source_as_of` fields are surfaced to consumers.

### Multi-Format Delivery

- REST API with GeoJSON and flat JSON responses.
- PostGIS-compatible WKB/WKT export alongside SQL Server export.
- CSV and Parquet bulk export for analytics teams.
- geoconv integration for on-demand format conversion to GeoPackage, Shapefile, and FlatGeobuf.

### Coverage Tier Model

| Tier | Coverage Level | Example Cities | AI Role |
| --- | --- | --- | --- |
| Tier 1 | Full authoritative sources | NYC, LA, Chicago, Toronto, Houston | Gap fill only where null |
| Tier 2 | Assessor + NSI + Overture | Phoenix, Denver, Atlanta, Calgary | Moderate gap fill with confidence flags |
| Tier 3 | NSI + Overture only | Mid-tier US cities, most of Canada outside Toronto | Primary fill with mandatory disclosure |
| Tier 4 | Overture / OSM only | International and rural regions | Heavy AI, clearly marked as estimated |

The coverage matrix is published in documentation, surfaced via an API `/coverage` endpoint, and included in every data delivery package. Consumers should never discover a coverage gap by accident.

## Phase 3 - AI Assistance

AI is suggest-only, never overwrites authoritative fields, and every prediction carries full provenance. The Phase 2 coverage tier model informs where AI is most active. Tier 3 and Tier 4 regions will have the highest AI prediction density.

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

Confidence suppression by tier:

- Tier 1: AI predictions emitted only where authoritative field is null.
- Tier 2: AI predictions emitted with explicit low-confidence flags.
- Tier 3: AI predictions are primary fill with mandatory disclosure to consumers.
- Tier 4: AI predictions are high-density estimates with clear consumer warnings.

## Phase 4 - Domain Extensions

Extension tables are additive and do not change the core schema.

Priority order is based on buyer readiness and deal speed:

| Priority | Vertical | Phase | Why This Order |
| --- | --- | --- | --- |
| 1 | Flood Monitoring | Phase 4 | Regulatory tailwind; FEMA, OSFI, and insurance mandates |
| 2 | Weather Risk | Phase 4 | Reinsurance and insurance buyers already have budget and procurement process |
| 3 | Emergency Response | Phase 4 | Municipal procurement is slower but large; start conversations in Phase 2 |
| 4 | Urban Planning | Phase 4 | Zoning and assessor data are already in Phase 2; extension is incremental |
| 5 | Oil and Gas | Phase 4 | High-value vertical but longer sales cycle; build relationships in Phase 3 |

Extension fields:

- Flood: flood zone, elevation, nearest water body, exposure category, basement indicators.
- Oil and Gas: distance to wells, pipelines, tanks, terminals, asset buffer relationships, exposure class.
- Weather: wind, hail, tornado, and storm exposure zones, roof class, severe-weather risk categories.
- Urban Planning: zoning, land use, parcel ID, year built, assessed value, use classification.
- Emergency Response: estimated occupants, critical facility flag, school, hospital, shelter tags.

## Phase 5 - Platform + Distribution

Delivery and documentation move earlier, so this phase focuses on commercialization and ecosystem positioning.

- Versioned release metadata and repeatable refresh workflow.
- Data quality SLA dashboard with per-source freshness and completeness tracking.
- Consumer-facing documentation and attribute data dictionary.
- Marketplace listings such as AWS Data Exchange, Snowflake Marketplace, and Google Cloud Marketplace.
- Webhook/change notification API for consumers who need real-time delta feeds.

## AI Role - Constraints

The AI model is a gap-filler and confidence scorer. It does not define source of truth.

| AI Is Allowed To | AI Is Never Allowed To |
| --- | --- |
| Fill null authoritative fields with predictions | Overwrite a non-null authoritative field |
| Score confidence on derived attributes | Emit a prediction without a confidence score |
| Flag anomalies in authoritative data | Silently replace a flagged value |
| Suggest source matches across datasets | Be the named source in `LoadSource` or `RawDataSource` |
| Operate on imagery/geometry in future phases | Change the provenance contract schema |

## Data Freshness Model

| Source | Refresh Cadence | Change Detection | Consumer Signal |
| --- | --- | --- | --- |
| NYC PLUTO / City Assessors | Quarterly, aligned to release | Record-level delta comparison | `last_refreshed` field + changelog |
| NSI/FEMA | Annual, aligned to FEMA release | Full reload with delta flagging | `source_as_of` field |
| Overture Maps | Monthly | Geometry + attribute delta detection | Webhook delta feed in Phase 5 |
| OSM | Weekly | Changeset monitoring via Overpass | `last_refreshed` field |
| AI Predictions | On-demand + batch refresh | Re-score on source record change | `PredictionModelVersion` field |

This model gives every consumer a documented freshness contract.

## GeoSentinel Integration

Structure Intelligence Database is the canonical structure data layer that GeoSentinel queries for crisis intelligence.

Integration path:

- Phase 1-2: Structure DB ships as standalone product; GeoSentinel queries it via internal API.
- Phase 3: AI confidence scores from Structure DB feed GeoSentinel risk weighting.
- Phase 4: Domain extension tables become hazard overlay foundations for GeoSentinel.
- Phase 5: Structure DB becomes an externally licensed data product; GeoSentinel becomes a premium application layer on top.

Long-term architecture:

- Structure Intelligence Database is the data moat.
- GeoSentinel is the intelligence platform.
- geoconv is the delivery format layer.

These are three distinct products with compounding value.

## Summary Of Changes From V1

| Area | V1 | V2 |
| --- | --- | --- |
| Data freshness | Not addressed | Refresh pipeline + cadence model in Phase 2 |
| Delivery formats | SQL Server only until Phase 5 | REST API + PostGIS + Parquet promoted to Phase 2 |
| Coverage gaps | Not addressed | Tier model + gap registry + coverage API in Phase 2 |
| GTM positioning | Data vendor story | Compliance infrastructure + audit-ready provenance story |
| Competitive moat | Unstated | Provenance contract + compliance angle + audit trail |
| AI constraints | Suggest-only | Suggest-only + tier-aware confidence suppression |
| Audit trail | Implied | Explicit schema fields from Phase 1 |
| GeoSentinel link | Not mentioned | Canonical data layer underneath GeoSentinel |

Confidential.
