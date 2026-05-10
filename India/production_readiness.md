# Production Readiness Notes

This folder is now the production work area for Indian metro structure layers. Keep the original root pipeline separate.

## Production Contract

The pipeline writes one row per structure polygon. `StructureID` is the stable join key for dashboards, planning reports, and future agents.

Core outputs:

- `India/data/output/{city}_{state}_india_structures.parquet`
- `India/data/output/{city}_{state}_india_structures.parquet.metadata.json`
- `India/data/output/structures_master.parquet`
- `India/data/output/structures_master.parquet.metadata.json`

The metadata sidecars record run time, city/state/country, bounds, row counts, source counts, and config values.

## Pipeline Separation

There are two separate production pipelines:

- `structure_pipeline.py`: builds the canonical structure layer. Only structure-related sources belong here.
- `processing_pipeline.py`: builds separate ML, deep-learning, hazard, and planning outputs, then creates a `StructureID` link table back to the structure layer.

Processing outputs:

- `India/data/processing/output/processing_layers.parquet`
- `India/data/processing/output/processing_layers.parquet.metadata.json`
- `India/data/processing/output/structure_processing_links.parquet`
- `India/data/processing/output/structure_processing_links.parquet.metadata.json`

Use `India/processing_sources.example.json` as the source-spec template for exported model layers. Keep model outputs in `data/processing/raw/`, not in the structure pipeline.

Processing source specs now support stable provenance fields:

- `source_family`: for example `nrsc_isro`, `survey_of_india`, `iudx`, `municipal_gis`, `heuristic_proxy`, or `model_export`
- `provenance_tier`: `authoritative`, `model`, `heuristic`, or `reference`
- `prediction_kind`: `authoritative_context`, `model_prediction`, `heuristic_baseline`, or `reference`

Use the authoritative example source specs to onboard the first real planning layers:

- `India/authoritative_sources_chennai.example.json`
- `India/authoritative_sources_bengaluru.example.json`

## Source Layer Rules

Use `source_registry.json` as the source inventory. The structure pipeline itself only attaches structure-related data:

- Overture Maps building footprints and attributes
- Microsoft Global ML Building Footprints
- OpenStreetMap building tags through OSMnx
- optional NSI/census fields, disabled by default for India
- optional parcel layers for parcel ID, address, land use, zoning, owner, value, year built, and parcel area

The broader source stack for later planning and agent work is:

- NRSC/ISRO Bhuvan as the core planning and satellite-derived layer source
- Survey of India as the authoritative base-map/statutory anchor
- IUDX for transport, utility, and operational urban datasets
- municipal GIS portals for local implementation layers

Verified national source notes:

- Survey of India District Planning Map Series lists district map names with free-download links and related Maps & Data navigation: https://surveyofindia.gov.in/pages/district-planning-map-series
- NRSC Bhuvan Urban and Infrastructure services list NUIS, urban growth monitoring, master-plan formulation, and related thematic urban services: https://www.nrsc.gov.in/nrscnew/Services_Bhuvan_UrbanInfrastructure.php
- IUDX describes a secure and controlled API-based data-sharing platform for Indian cities: https://iudx.org.in/platform/

Recommended task routing:

- Master planning, zoning, land-use change: NRSC + SoI + local master-plan GIS
- Transport, utilities, service delivery: IUDX + municipal operational datasets
- Statutory or legal-grade base mapping: SoI first, then local cadastral / land-record layers
- Urban growth, sprawl, environmental suitability: NRSC satellite imagery plus GIS overlays

Local parcel sources can be:

- GeoJSON
- GeoPackage
- GeoParquet / Parquet
- CSV or TSV with WKT
- CSV or TSV with longitude/latitude

Relative paths are resolved against the `India` folder when possible. This keeps `data/raw/...` working whether Jupyter is started from the repo root or from `India/`.

Future model or planning layers should be produced outside `structure_pipeline.py` and joined later by `StructureID` or spatial relationship. Do not add those fields back into the structure schema.

Processing CLI example:

```bash
python India/processing_pipeline.py \
  --source-config India/processing_sources.example.json \
  --structure-path India/data/output/structures_master.parquet
```

Production-style wrapper commands from the repo root:

```bash
.venv/bin/python scripts/run_india_pipeline.py --config India/pipeline_config.example.json
.venv/bin/python scripts/run_india_processing.py --config India/processing_pipeline_config.example.json
```

Authoritative dry-run examples:

```bash
.venv/bin/python scripts/run_india_processing.py --config India/authoritative_processing_chennai.example.json --dry-run
.venv/bin/python scripts/run_india_processing.py --config India/authoritative_processing_bengaluru.example.json --dry-run
```

Production verification command:

```bash
.venv/bin/python India/production_verification.py --config India/production_verification.example.json
```

Add `--dry-run` to validate config, logging, paths, and dataclass fields without running the pipeline.

## Strict Mode

Default notebook behavior is permissive: optional missing layers are skipped with a message. For production runs, enable strict mode when configured sources are expected to exist:

```python
config = PipelineConfig(
    country="India",
    strict_sources=True,
    fail_on_empty_output=True,
    write_run_metadata=True,
)
```

CLI equivalents:

```bash
python India/structure_pipeline.py \
  --place "Chennai, Tamil Nadu" \
  --strict-sources \
  --fail-on-empty-output
```

Use strict mode for scheduled or published runs. Keep permissive mode for exploration.

## Validation Checks

Run these before trusting a pipeline change:

```bash
.venv/bin/python -m py_compile India/structure_pipeline.py
.venv/bin/python -m py_compile India/processing_pipeline.py
.venv/bin/python -m unittest discover -s India/tests
```

The tests cover:

- India defaults and state aliases
- empty-output schema stability
- structure-only output schema stability
- structure attribute finalization
- strict missing-source failures
- duplicate `StructureID` validation
- processing-layer standardization
- structure-to-processing spatial link generation
- mixed point/polygon processing-layer linkage

## Before Agents

Before adding agents, the base pipeline should pass these gates for Chennai:

- boundary geocoding is stable
- footprint sources complete or intentionally disabled
- parcel sources attach to nonzero structures when configured
- output metadata exists
- no duplicate `StructureID`
- no invalid geometries
- final output contains only the approved structure columns
