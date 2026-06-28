# Structure Exposure Layer

The structure exposure layer connects canonical building records to ward, city, hazard, and infrastructure intelligence. It is designed as a strict bridge between the Structures pipeline and the India Urban Intelligence dashboard.

## Role

The Structures pipeline answers:

- what structure exists
- where it is
- which attributes are known
- where each attribute came from
- how fresh and complete the record is

The urban intelligence system answers:

- which hazard or stress context applies
- which ward or asset area is affected
- what evidence supports the result
- what uncertainty and limitations remain

The exposure layer joins these two systems without inventing missing attributes or hazard outcomes.

## Production Gates

The exposure builder is strict by default:

- canonical structure release gates must pass
- ward geometries must be valid
- ward ids must be non-empty and unique
- every structure must assign to exactly one ward
- ambiguous ward assignments are blocked
- unassigned structures are blocked unless explicitly allowed
- missing structure attributes are reported as completeness gaps
- AI or model outputs cannot be used as authoritative source fields

## Artifact

The main dashboard-ready artifact is:

```text
chennai_structure_exposure_features.json
```

Each ward record includes:

- structure count
- residential, public, and other grouped structure counts
- known unit total
- known occupant total
- story summaries
- footprint area totals
- attribute completeness
- datasource completeness
- source counts
- coverage tiers
- refresh timestamps

## Operator Command

```bash
python scripts/build_structure_exposure.py \
  --structures examples/india_chennai_refresh_source.csv \
  --wards /path/to/gcc_divisions_wards.geojson \
  --ward-id-column ward_no \
  --expected-ward-count 200 \
  --output data/derived/chennai_structure_exposure_features.json
```

Use `--allow-unassigned` only for exploratory runs. Production runs should keep strict assignment enabled.

## Product Paths

### Urban Intelligence System

The structure exposure layer becomes one evidence input in the Chennai and Tamil Nadu urban intelligence dashboard. The dashboard can use it for:

- ward-level exposed structure counts
- public structure screening
- occupant exposure estimates where source-backed values exist
- structure datasource and completeness panels
- joins with flood, rainfall, elevation, land-cover, road, and water layers

Suggested API endpoints in the urban intelligence system:

- `/v1/india/tamil_nadu/chennai/structure-exposure`
- `/v1/india/tamil_nadu/chennai/structure-exposure/{ward_no}`
- `/v1/india/tamil_nadu/chennai/structures`

### Standalone Structure Product

The same canonical structure database can also stand alone as a data product for teams that need building attributes without the full hazard dashboard. In that path, the core surfaces are:

- canonical structure table
- structure map
- provenance and confidence table
- refresh runs
- coverage registry
- release manifest
- exports through API, SQL Server sync, PostGIS/WKT, CSV, Parquet, and GeoJSON

Both paths use the same canonical source of truth. The difference is presentation: one path focuses on urban risk and operations, while the other focuses on reusable structure data.

## Boundary

This layer does not claim flood impact, emergency status, official damage, or calibrated probability. Those outputs belong to the urban intelligence and model-governance layers after their evidence gates pass.
