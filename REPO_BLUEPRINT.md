# Structures Repo Blueprint

This repo builds building and structure datasets from geospatial sources. It has a general root pipeline and an India-specific workflow for structure intelligence, processing layers, and downstream planning analysis.

## What This Repo Does

```mermaid
flowchart LR
    A["Input Sources"] --> B["Structure Pipelines"]
    B --> C["Canonical Structure Tables"]
    C --> D["Processing / Planning Layers"]
    D --> E["Dashboards, Reports, Analysis, Agents"]

    A1["Overture Maps"] --> A
    A2["Microsoft Building Footprints"] --> A
    A3["OpenStreetMap / OSMnx"] --> A
    A4["Parcels / Local GIS"] --> A
    A5["India planning and model outputs"] --> D
```

The main output is a structure-level geospatial table: one row per building footprint, with IDs and optional enrichment fields. The India workflow keeps structure data separate from model, planning, hazard, and deep-learning layers, then links those layers back to structures by `StructureID` or spatial relationship.

## Main Use Cases

- Build city-level building footprint datasets.
- Merge Overture, Microsoft, OSM, parcel, census, and optional source attributes.
- Produce a stable structure table for GIS analysis, dashboards, or downstream systems.
- Run India-specific city workflows with separate processing layers for segmentation, change detection, flood prediction, and urban planning context.
- Validate production-style runs with JSON configs and repeatable commands.

## Repo Map

```mermaid
flowchart TB
    R["Repo Root"] --> RP["structure_pipeline.py<br/>Root / USA-style structure pipeline"]
    R --> RT["scripts/run_root_pipeline.py<br/>Production wrapper"]
    R --> RU["pipeline_utils.py<br/>Shared geospatial and metadata helpers"]
    R --> RR["pipeline_runtime.py<br/>Config, logging, validation helpers"]
    R --> RC["configs/root_pipeline.example.json"]
    R --> PR["PRODUCTION_RUNBOOK.md"]
    R --> I["India/"]
    R --> T["tests/"]

    I --> ISP["India/structure_pipeline.py<br/>India canonical structures"]
    I --> IPP["India/processing_pipeline.py<br/>India model / planning layers"]
    I --> IRC["India/pipeline_config.example.json"]
    I --> IPC["India/processing_pipeline_config.example.json"]
    I --> ISR["India/source_registry.json"]
    I --> IPS["India/processing_sources.example.json"]
    I --> IPR["India/production_readiness.md"]
    I --> IT["India/tests/"]
```

## Pipeline Flow

### Root Structure Pipeline

```mermaid
flowchart LR
    C["configs/root_pipeline.example.json"] --> W["scripts/run_root_pipeline.py"]
    W --> P["structure_pipeline.py"]
    P --> S1["City boundary"]
    P --> S2["Overture footprints"]
    P --> S3["Microsoft footprints"]
    P --> S4["OSM tags"]
    P --> S5["NSI / Census / Parcels"]
    S1 --> O["data/output/*.parquet"]
    S2 --> O
    S3 --> O
    S4 --> O
    S5 --> O
```

### India Structure Pipeline

```mermaid
flowchart LR
    C["India/pipeline_config.example.json"] --> W["scripts/run_india_pipeline.py"]
    W --> P["India/structure_pipeline.py"]
    P --> B["Boundary + footprints + parcel sources"]
    B --> O1["India/data/output/{city}_structures.parquet"]
    B --> O2["India/data/output/structures_master.parquet"]
    B --> M["Metadata sidecars"]
```

### India Processing Pipeline

```mermaid
flowchart LR
    C["India/processing_pipeline_config.example.json"] --> W["scripts/run_india_processing.py"]
    S["India/processing_sources.example.json"] --> W
    W --> P["India/processing_pipeline.py"]
    P --> L["processing_layers.parquet"]
    P --> X["structure_processing_links.parquet"]
    ST["India/data/output/structures_master.parquet"] --> P
```

## Key Files

| File | Purpose |
| --- | --- |
| `structure_pipeline.py` | Root structure pipeline. Builds enriched structure polygons from footprint and enrichment sources. |
| `India/structure_pipeline.py` | India-specific canonical structure pipeline. Defaults to India paths and disables US-specific NSI/census by default. |
| `India/processing_pipeline.py` | Separate India processing-layer pipeline for segmentation, flood, change detection, and urban planning outputs. |
| `pipeline_utils.py` | Shared helpers for slugs, geometry cleaning, CRS selection, metadata sidecars, and path/source utilities. |
| `pipeline_runtime.py` | Production execution helpers for config loading, logging, validation, and dry-run checks. |
| `scripts/run_root_pipeline.py` | Production-style wrapper for the root pipeline. |
| `scripts/run_india_pipeline.py` | Production-style wrapper for the India structure pipeline. |
| `scripts/run_india_processing.py` | Production-style wrapper for the India processing pipeline. |
| `PRODUCTION_RUNBOOK.md` | Short command reference for production-style runs. |
| `India/production_readiness.md` | India pipeline contract, validation expectations, and readiness notes. |
| `India/source_registry.json` | India source inventory and authority notes. |

## How To Use This Repo

### 1. Install Dependencies

Use the existing virtual environment if it already exists:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Optional India model-processing dependencies are listed in:

```bash
India/requirements-geoai.txt
```

### 2. Validate Configs Without Running

Dry runs validate config shape, logging level, dataclass fields, and protected paths.

```bash
.venv/bin/python scripts/run_root_pipeline.py --config configs/root_pipeline.example.json --dry-run
.venv/bin/python scripts/run_india_pipeline.py --config India/pipeline_config.example.json --dry-run
.venv/bin/python scripts/run_india_processing.py --config India/processing_pipeline_config.example.json --dry-run
```

### 3. Run The Root Pipeline

Edit `configs/root_pipeline.example.json`, then run:

```bash
.venv/bin/python scripts/run_root_pipeline.py --config configs/root_pipeline.example.json
```

### 4. Run The India Structure Pipeline

Edit `India/pipeline_config.example.json`, then run:

```bash
.venv/bin/python scripts/run_india_pipeline.py --config India/pipeline_config.example.json
```

### 5. Run India Processing Layers

First produce or provide `India/data/output/structures_master.parquet`. Then edit:

- `India/processing_pipeline_config.example.json`
- `India/processing_sources.example.json`

Run:

```bash
.venv/bin/python scripts/run_india_processing.py --config India/processing_pipeline_config.example.json
```

## Config Pattern

```json
{
  "logging": {
    "level": "INFO"
  },
  "places": [
    {
      "city": "Chennai",
      "state": "Tamil Nadu"
    }
  ],
  "config": {
    "country": "India",
    "strict_sources": false,
    "write_run_metadata": true
  }
}
```

Runtime validation rejects:

- unknown config fields
- missing or malformed `places`
- invalid logging levels
- paths pointing inside `.venv`

## Output Contract

```mermaid
flowchart TB
    A["Structure output"] --> B["One row per structure"]
    B --> C["Stable StructureID"]
    B --> D["Geometry preserved in CRS-aware GeoParquet"]
    B --> E["Metadata sidecar when enabled"]
    C --> F["Join key for processing layers"]
```

The India structure pipeline writes canonical structures to `India/data/output/`. The India processing pipeline writes processing layers and structure links to `India/data/processing/output/`.

Do not commit generated raw data, caches, output tables, `.venv`, `__pycache__`, or notebook checkpoints.

## Development Checklist

Before trusting a change:

```bash
.venv/bin/python -c "import py_compile; py_compile.compile('structure_pipeline.py', doraise=True); py_compile.compile('India/structure_pipeline.py', doraise=True); py_compile.compile('India/processing_pipeline.py', doraise=True)"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s India/tests
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests
```

For India changes, keep these docs aligned:

- `India/pipeline_change_log.md`
- `India/production_readiness.md`
- `India/source_registry.json`

## Mental Model

Use `structure_pipeline.py` or `India/structure_pipeline.py` to create the canonical building table. Use `India/processing_pipeline.py` only for model, hazard, planning, and other analytical overlays. Keep structure identity stable, keep raw inputs separate, and use JSON configs for repeatable runs.
