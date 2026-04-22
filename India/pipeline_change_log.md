# India Pipeline Change Log

This log records user-requested changes and implemented changes for the India structure and urban-planning pipeline.

## 2026-04-19 11:46:57 EDT

Initial retrospective log created. Earlier India-pipeline changes were completed before this log file existed, so this entry consolidates the requested work and implementation state as of this timestamp.

### Request: Create India Working Copy

User requested:

- Create a copy of the original `structure_pipeline.py`.
- Create a copy of `test.ipynb`.
- Move both into a new folder called `India`.
- Use this as the starting point for Indian cities and states.

Implemented:

- Created `India/`.
- Copied the pipeline to `India/structure_pipeline.py`.
- Copied the notebook to `India/test.ipynb`.
- Kept the original root pipeline separate.

### Request: Adapt India Folder For Indian Cities, GeoAI, HuggingFace, And Deep Learning

User requested:

- Edit only the `India` folder.
- Prepare the pipeline for Indian cities and states.
- Support GeoAI models from HuggingFace and other deep-learning models.

Implemented:

- Changed India pipeline defaults:
  - `country="India"`
  - `use_nsi=False`
  - `use_census=False`
  - `use_geoai=True`
  - `use_huggingface_models=False`
- Added Indian state and union-territory abbreviation normalization, including examples such as `TN -> Tamil Nadu`, `KA -> Karnataka`, and `MH -> Maharashtra`.
- Added generic GeoAI prediction ingestion:
  - GeoJSON
  - GeoPackage
  - GeoParquet / Parquet
  - CSV / TSV with WKT
  - CSV / TSV with longitude and latitude
- Added generic GeoAI output columns:
  - `GeoAI_Label`
  - `GeoAI_Score`
  - `GeoAI_Model`
  - `GeoAI_Source`
  - `GeoAI_RecordCount`
  - `GeoAI_MatchMethod`
- Added optional HuggingFace pipeline hooks with lazy imports so `transformers` is not required unless enabled.
- Added optional HuggingFace output columns:
  - `HuggingFace_Label`
  - `HuggingFace_Score`
  - `HuggingFace_Model`
  - `HuggingFace_Task`
  - `HuggingFace_InputColumn`
- Added `India/requirements-geoai.txt` for optional deep-learning dependencies.
- Updated `India/test.ipynb` with India-specific examples and configuration.

### Request: Support SegFormer, U-Net, Change Detection, ConvLSTM, And ST-Transformers

User requested:

- Prepare the pipeline for SegFormer and U-Net.
- Support change detection.
- Support ConvLSTM and ST-Transformers for flood prediction.
- Focus on flood prediction and urban planning for Indian metro cities, especially Chennai.

Implemented:

- Added dedicated SegFormer / U-Net segmentation channel:
  - `Segmentation_Label`
  - `Segmentation_Score`
  - `Segmentation_Model`
  - `Segmentation_Source`
  - `Segmentation_Task`
  - `Segmentation_RecordCount`
  - `Segmentation_MatchMethod`
- Added dedicated change-detection channel:
  - `Change_Label`
  - `Change_Score`
  - `Change_Model`
  - `Change_Source`
  - `Change_FromDate`
  - `Change_ToDate`
  - `Change_Area_m2`
  - `Change_RecordCount`
  - `Change_MatchMethod`
- Added dedicated flood-prediction channel for ConvLSTM / ST-Transformer outputs:
  - `FloodRisk`
  - `FloodRiskScore`
  - `FloodDepthM`
  - `FloodProbability`
  - `FloodForecastHorizonHr`
  - `FloodModel`
  - `FloodSource`
  - `FloodScenario`
  - `FloodTimestamp`
  - `FloodMatchMethod`
- Added dedicated urban-planning model channel:
  - `UrbanPlan_Label`
  - `UrbanPlan_Score`
  - `UrbanPlan_Model`
  - `UrbanPlan_Source`
  - `UrbanPlan_Horizon`
  - `UrbanPlan_MatchMethod`
- Updated `India/test.ipynb` to default to Chennai, Tamil Nadu.
- Added example configuration blocks for:
  - segmentation sources
  - change-detection sources
  - flood-prediction sources
  - urban-planning sources
- Added `India/modeling_plan.md` with a Chennai-first modeling plan.

### Request: Production-Ready And Fool-Proof Before Agents

User requested:

- Get the structure pipeline and other layers ready first.
- Make it production ready and more fool-proof.
- Move to agents only after the pipeline is solid.

Implemented:

- Added stable `OUTPUT_COLUMNS` schema for final outputs.
- Added config validation.
- Added production flags:
  - `strict_sources`
  - `fail_on_empty_output`
  - `write_run_metadata`
- Added source path resolution so relative `data/raw/...` paths resolve against the `India` folder when possible.
- Added strict missing-source behavior for parcels and model layers.
- Added output validation before writing:
  - CRS must exist.
  - `StructureID` must exist.
  - `StructureID` must not contain nulls.
  - `StructureID` must not contain duplicates.
  - geometries must not be null.
  - geometries must be valid.
- Added metadata sidecars:
  - `*.parquet.metadata.json`
- Metadata includes:
  - run timestamp
  - city/state/country
  - bounds
  - row counts
  - source counts
  - config snapshot
- Changed parcel area fallback CRS from U.S.-specific `EPSG:5070` to global equal-area `EPSG:6933`.
- Added `India/production_readiness.md`.
- Added `India/tests/test_pipeline_contracts.py`.
- Added regression tests for:
  - India defaults and state aliases
  - empty-output schema stability
  - segmentation attachment
  - flood attachment
  - strict missing-source failures
  - duplicate `StructureID` validation

Validation performed:

```bash
.venv/bin/python -m py_compile India/structure_pipeline.py
.venv/bin/python -m unittest discover -s India/tests
```

Result:

```text
Ran 6 tests
OK
```

### Request: Add NRSC, Survey Of India, IUDX, And Municipal GIS Source Strategy

User requested:

- Use NRSC / ISRO urban geospatial layers as the core planning layer.
- Anchor them with Survey of India base maps.
- Enrich with IUDX and municipal GIS for Chennai, Mumbai, Bengaluru, and Hyderabad.
- Treat sources differently by task:
  - master planning / zoning / land-use change
  - transport, utilities, and service delivery
  - statutory or legal-grade base mapping
  - urban growth / sprawl / environmental suitability

Implemented:

- Added `India/source_registry.json`.
- Added national source registry entries for:
  - NRSC / ISRO Bhuvan
  - Survey of India
  - IUDX
- Added metro source entries for:
  - Chennai
  - Mumbai
  - Bengaluru
  - Hyderabad
- Added source strategy mapping:
  - NRSC / ISRO for core planning, urban growth, land use, sprawl, environmental suitability, and flood/water-resource context.
  - Survey of India for statutory and base-map anchoring.
  - IUDX for transport, utilities, services, and operational feeds.
  - Municipal GIS for local implementation layers.
- Added a dedicated authoritative planning-overlay channel:
  - `PlanningLayer_Name`
  - `PlanningLayer_Category`
  - `PlanningLayer_Value`
  - `PlanningLayer_Source`
  - `PlanningLayer_Authority`
  - `PlanningLayer_Access`
  - `PlanningLayer_RecordCount`
  - `PlanningLayer_MatchMethod`
- Added `planning_overlay_sources` to `PipelineConfig`.
- Added pipeline integration for planning overlays.
- Added CLI support:
  - `--planning-overlay-source city_slug=path`
- Updated `India/test.ipynb` with NRSC and SoI planning-overlay examples.
- Updated `India/production_readiness.md` with task-based source routing.
- Updated `India/modeling_plan.md` to place authoritative planning overlays before future urban-planning agents.
- Added regression test coverage for authoritative planning overlays.

Validation performed:

```bash
.venv/bin/python -m py_compile India/structure_pipeline.py
.venv/bin/python -m unittest discover -s India/tests
```

Result:

```text
Ran 7 tests
OK
```

### Current Production Artifacts

Important files now maintained under `India/`:

- `India/structure_pipeline.py`
- `India/test.ipynb`
- `India/modeling_plan.md`
- `India/production_readiness.md`
- `India/source_registry.json`
- `India/requirements-geoai.txt`
- `India/tests/test_pipeline_contracts.py`
- `India/pipeline_change_log.md`

### Current Direction

Pipeline-first approach is active:

1. Harden structure pipeline and planning layers.
2. Validate Chennai first.
3. Add Mumbai, Bengaluru, and Hyderabad.
4. Only then introduce multiple urban-planning agents.

## 2026-04-19 12:27:52 EDT

### Request: Remove Generic HuggingFace Columns From The India Pipeline

User requested:

- Remove `HuggingFace_Label`.
- Remove `HuggingFace_Score`.
- Remove `HuggingFace_Model`.
- The generic HuggingFace output path is not needed in this pipeline.

Implemented:

- Removed generic HuggingFace table-inference support from `India/structure_pipeline.py`.
- Removed the generic HuggingFace config fields:
  - `use_huggingface_models`
  - `huggingface_models`
  - `huggingface_cache_dir`
- Removed the generic HuggingFace output columns:
  - `HuggingFace_Label`
  - `HuggingFace_Score`
  - `HuggingFace_Model`
  - `HuggingFace_Task`
  - `HuggingFace_InputColumn`
- Removed the generic HuggingFace post-processing call from the city build flow.
- Removed CLI support for `--use-huggingface-models`.
- Updated `India/test.ipynb` to remove generic HuggingFace configuration and output examples.
- Cleared stale notebook execution outputs so old HuggingFace columns are not shown in rendered cell outputs.
- Updated `India/production_readiness.md` and `India/requirements-geoai.txt` to describe model outputs as exported GeoAI/deep-learning layers rather than generic HuggingFace table inference.

Kept:

- `GeoAI_Model`
- `Segmentation_Model`
- `Change_Model`
- `FloodModel`
- `UrbanPlan_Model`

Reason:

- These model-specific provenance fields are still needed for exported segmentation, change-detection, flood-prediction, and urban-planning layers.

## 2026-04-19 12:34:41 EDT

### Request: Keep The India Structure Pipeline Structure-Only

User requested:

- Remove all active GeoAI, segmentation, change-detection, flood, urban-planning, planning-layer, and generic HuggingFace fields from the India structure pipeline.
- Keep only structure-related data in `India/structure_pipeline.py`.

Implemented:

- Removed the remaining active model and planning-layer schema channels from `India/structure_pipeline.py`.
- Removed model and planning-layer config fields and CLI arguments from the India pipeline.
- Removed model and planning-layer attachment calls from the city build flow.
- Updated `India/test.ipynb` so the notebook config, coverage checks, and output examples are structure-only.
- Updated `India/tests/test_pipeline_contracts.py` to assert the approved structure-only output schema.
- Updated `India/production_readiness.md` to define the current production contract as Overture, Microsoft, OSM, optional NSI/census, and optional parcel data only.
- Updated `India/modeling_plan.md`, `India/source_registry.json`, and `India/requirements-geoai.txt` so future model work is documented as separate layer or agent work outside `structure_pipeline.py`.
- Migrated existing generated parquet outputs in `India/data/output/` down to the approved structure-only schema.
- Updated existing output metadata sidecars with `schema_contract=structure_only`, current output columns, and config keys that exist in the current pipeline.

Current structure pipeline output families:

- structure identity and location
- footprint source provenance
- Overture, Microsoft, OSM, optional NSI/census identifiers and attributes
- normalized structure type, name, height, stories, units, occupancy estimate, and source fields
- optional parcel attributes and parcel match method
- footprint area, Microsoft confidence, parts flag, and geometry

## 2026-04-19 13:56:11 EDT

### Request: Record Verified National Source Notes

User provided source notes for:

- Survey of India District Planning Map Series
- NRSC Bhuvan Urban and Infrastructure services
- IUDX platform

Implemented:

- Verified the public pages and added concise source notes to `India/source_registry.json`.
- Added the same national source notes to `India/production_readiness.md`.
- Kept `India/structure_pipeline.py` unchanged because these sources are planning/context references, not structure-schema fields.

## 2026-04-19 14:02:18 EDT

### Request: Split Structure And ML Processing Pipelines

User clarified:

- `structure_pipeline.py` should contain only sources related to structure data.
- ML and deep-learning work should live in a separate processing pipeline/script.

Implemented:

- Added `India/processing_pipeline.py` as the separate ML/deep-learning processing pipeline.
- Added `India/processing_sources.example.json` as a template for exported model-layer sources.
- The processing pipeline writes normalized model/context layers to `India/data/processing/output/processing_layers.parquet`.
- The processing pipeline writes structure links to `India/data/processing/output/structure_processing_links.parquet`.
- Processing links are keyed by `StructureID`, so the base structure parquet stays structure-only.
- Added processing-pipeline contract tests for layer standardization, polygon spatial links, and point spatial links.
- Updated `India/modeling_plan.md`, `India/production_readiness.md`, and `India/requirements-geoai.txt` to document the split.

Current split:

- Structure pipeline: Overture, Microsoft, OSM, optional NSI/census, optional parcels.
- Processing pipeline: segmentation, change detection, flood prediction, urban planning, planning context, and other ML/deep-learning outputs.
