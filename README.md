# Building Footprints Pipeline

Python pipeline for building enriched structure polygons for US cities.

The pipeline combines building footprints and attributes from public sources such as Overture Maps, Microsoft building footprints, OpenStreetMap through OSMnx, USACE National Structure Inventory, Census ACS, and optional parcel layers.

## Outputs

For each city, the pipeline writes a GeoParquet file under `data/output/` with structure geometry and normalized attributes such as:

- structure type
- estimated residential units
- estimated stories
- estimated occupant count
- source flags and confidence fields
- optional parcel attributes when parcel data is provided

The combined multi-city output is written to `data/output/structures_master.parquet`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## CLI Usage

```bash
python structure_pipeline.py --place "Chicago, Illinois"
```

Multiple cities can be processed in one run:

```bash
python structure_pipeline.py \
  --place "Chicago, Illinois" \
  --place "Houston, Texas"
```

Optional parcel data can be attached by city slug:

```bash
python structure_pipeline.py \
  --place "Chicago, Illinois" \
  --parcel-source chicago_illinois_usa=/path/to/parcels.gpkg
```

## Data Access

Most sources are public and do not require an API key. The script does require internet access for downloads unless cached files already exist locally. Overture downloads use the `overturemaps` Python package CLI.

Use `--no-download` to force the pipeline to use already cached local files only.

## Notebook

`test.ipynb` provides an interactive workflow for configuring cities, running the pipeline, and inspecting the output.
