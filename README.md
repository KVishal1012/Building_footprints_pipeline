# Structure Intelligence Database

Production-oriented structure database for enriched building and structure records across US Census places in the 50 states plus DC.

The goal is a trusted structure intelligence database for urban planning, flood monitoring, oil and gas, weather monitoring, emergency response, insurance, and infrastructure analysis. The Python pipeline, SQL Server export, and AI models are supporting systems; the end product is the queryable structure database.

Every major attribute should answer:

- What is the value?
- Where did it come from?
- How confident is it?
- Was it authoritative, derived, estimated, or AI-suggested?

See [docs/product_map.md](docs/product_map.md) for the v2 product map, including data freshness, multi-format delivery, coverage tiers, compliance positioning, and GeoSentinel integration. The Supabase-first product architecture is documented in [docs/database_architecture.md](docs/database_architecture.md). Consumer-facing contracts are documented in [docs/data_dictionary.md](docs/data_dictionary.md), [docs/coverage_tiers.md](docs/coverage_tiers.md), [docs/freshness_sla.md](docs/freshness_sla.md), and [docs/provenance_contract.md](docs/provenance_contract.md).

## Manhattan Demo Package

The Manhattan Structure Intelligence demo in [demo_packages/manhattan_demo](demo_packages/manhattan_demo) includes sample canonical structures, attribute provenance, coverage/completeness metrics, a release manifest with passing QA gates, and a one-page implementation brief.

Regenerate it from the committed Manhattan fixture:

```bash
python scripts/build_manhattan_demo_package.py
```

## Chennai / Tamil Nadu Demo Package

The India branch starts with Chennai as the proof market and Tamil Nadu as the expansion path. The Chennai demo package is generated into [demo_packages/chennai_demo](demo_packages/chennai_demo) and includes canonical sample rows, provenance, coverage/completeness metrics, a release manifest with passing QA gates, and a one-page Tamil Nadu implementation brief.

Regenerate it from the committed Chennai fixture:

```bash
python scripts/build_chennai_demo_package.py
```

The pipeline uses Census TIGER/Line place boundaries for reproducible city coverage, Overture Maps, Microsoft Global ML Building Footprints, SQL Server authoritative sources, USACE NSI and ACS, optional parcel layers, and optional OSM enrichment.

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

Run all Census places in one or more states:

```bash
python structure_pipeline.py --state CA --output-dir data/output --source-version latest
```

Run all Census places in the 50 states plus DC:

```bash
python structure_pipeline.py --all-us-cities --output-dir data/output --source-version latest
```

Optional parcel data can be attached by place GEOID or city slug:

```bash
python structure_pipeline.py \
  --place "Chicago, Illinois" \
  --parcel-source 1714000=/path/to/parcels.gpkg
```

A SQL Server table or query with a geometry/geography column can be used as a footprint source. Store the SQLAlchemy connection string in an environment variable so credentials stay out of command history:

```bash
export STRUCTURES_SQLSERVER_URL='mssql+pyodbc:///?odbc_connect=Driver%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BServer%3Dtcp%3Aserver.example.com%2C1433%3BDatabase%3Dgis%3BUID%3Duser%3BPWD%3Dpassword%3BEncrypt%3Dyes'
python structure_pipeline.py \
  --place "Chicago, Illinois" \
  --sql-table dbo.BuildingFootprints \
  --sql-geom-column Shape \
  --sql-id-column BuildingID \
  --sql-structure-type-column UseType \
  --sqlserver-geometry-methods
```

For custom SQL Server queries, return a WKB/WKT geometry column and alias it to the configured `--sql-geom-column`.

A SQL Server baseline table can also define the area of interest. The pipeline reads the baseline geometry, buffers it in meters, captures structures around that buffer, and writes `BaselineID`, `BaselineDistance_m`, and `BaselineBuffer_m` to the output:

```bash
python structure_pipeline.py \
  --place "Houston, Texas" \
  --baseline-sql-table dbo.AssetBaseline \
  --baseline-sql-geom-column Shape \
  --baseline-sql-id-column AssetID \
  --baseline-buffer-meters 250 \
  --baseline-sql-where "Status = 'Active'" \
  --baseline-sqlserver-geometry-methods
```

To view the final output as a dataframe in Python and export it as the last step to SQL Server, enable the dataframe preview and provide an output table. The SQL export writes geometry as WKT by default in `geometry_wkt`.

```bash
python structure_pipeline.py \
  --place "Chicago, Illinois" \
  --no-local-outputs \
  --show-dataframe \
  --dataframe-preview-rows 20 \
  --export-sqlserver-table dbo.StructuresOutput \
  --export-sqlserver-if-exists append
```

The same final dataframe is available directly from Python:

```python
from structures_pipeline.config import PipelineConfig
from structures_pipeline.pipeline import run_pipeline

config = PipelineConfig(
    return_dataframe=True,
    write_local_outputs=False,
    sql_export={
        "connection_env": "STRUCTURES_SQLSERVER_URL",
        "table": "dbo.StructuresOutput",
        "if_exists": "append",
    },
)

result = run_pipeline(place_specs=[{"city": "Chicago", "state": "Illinois"}], config=config)
df = result["dataframe"]
print(df.head())
```

For SQL Server-only runs, use the dedicated module to specify server name, database name, baseline table, output table, SRID, and buffer in one place:

Create a local input module:

```bash
cp sql_server_inputs.example.py sql_server_inputs.py
```

Edit `sql_server_inputs.py`, then run:

```bash
python scripts/run_sql_server_pipeline.py
```

The local `sql_server_inputs.py` file is ignored by Git so server names and credentials do not get committed. The runner reads:

- `PLACE_SPECS`, `STATE_FILTERS`, or `ALL_US_CITIES`
- `SQL_SERVER`
- `BASELINE`
- `FOOTPRINTS`
- `OUTPUT`
- `PIPELINE_OVERRIDES`

Use `FOOTPRINTS` for the authoritative structure table loaded through SQL Server. SQL Server is recorded as the load mechanism, not the raw authority. Set `raw_data_source` and the per-attribute source labels to the real upstream source, such as `nyc_pluto`, `nyc_building_footprints`, `assessor`, or another agency dataset. Overture, OSM, NSI, ACS, and parcels then act as fallback/enrichment sources only where the authoritative raw source does not provide a value.

You can also call the SQL Server module directly from Python:

```python
from structures_pipeline.sql_server import (
    SqlServerPipelineSettings,
    run_sql_server_pipeline,
)

settings = SqlServerPipelineSettings(
    server_name="tcp:server.example.com,1433",
    database_name="gis",
    baseline_table="dbo.AssetBaseline",
    baseline_geom_column="Shape",
    baseline_id_column="AssetID",
    baseline_buffer_value=250,
    baseline_srid=4326,
    footprint_table="dbo.AuthoritativeStructures",
    footprint_raw_data_source="nyc_pluto",
    footprint_id_column="StructureID",
    footprint_structure_type_column="StructureType",
    footprint_units_column="NumUnits",
    footprint_stories_column="NumStories",
    footprint_height_column="HeightM",
    footprint_occupant_count_column="OccupantCount",
    footprint_structure_type_source="nyc_pluto_land_use",
    footprint_units_source="nyc_pluto_units_total",
    footprint_stories_source="nyc_pluto_num_floors",
    footprint_height_source="nyc_pluto_height_roof",
    footprint_occupant_count_source="nyc_pluto_occupancy",
    output_table="dbo.StructuresOutput",
    username="user",
    password="password",
)

result = run_sql_server_pipeline(
    settings,
    place_specs=[{"city": "Houston", "state": "Texas"}],
)
df = result["dataframe"]
print(df.head())
```

`baseline_buffer_value` is converted to meters before the pipeline buffers the baseline. EPSG:4326 and EPSG:4269 are treated as meter-based SQL Server geography buffers, common US-foot SRIDs are converted to meters, and `buffer_unit_to_meters` can be set for any custom SRID.

The SQL Server module defaults to table-only mode and does not write local JSON or parquet outputs. For CLI runs, use `--no-local-outputs` to skip city parquet, master parquet, QA parquet, and manifest JSON files.

Use `--no-download` to force cached local files only. Use `--use-osm` only for small/debug runs because OSM enrichment calls Overpass through OSMnx.

## Outputs

When local outputs are enabled, the pipeline writes:

- City GeoParquet: `data/output/cities/{statefp}/{place_geoid}_{city_slug}_structures.parquet`
- Master dataset: `data/output/structures_master/structures_master.parquet`
- Run manifest: `data/output/manifests/latest_run.json`
- QA metrics: `data/output/qa/city_metrics.parquet`

Required attributes include `StructureType`, `NumUnits`, `NumStories`, `FootprintArea_m2`, `FootprintArea_sqft`, `OccupantCount`, optional baseline fields, source/method/confidence fields, source release fields, and geometry.

## Product Architecture

The product architecture is Supabase/Postgres-first. SQL Server is an optional enterprise delivery sync, not the canonical database.

```text
Upstream Sources
PLUTO, Overture, NSI, Assessors, Parcels
        |
        v
Python Ingestion + QA Service
Railway / Fly.io / scheduled job
        |
        +--> Supabase: staging.raw_structures
        |       Raw source drops, source snapshots, provenance
        |
        +--> Change Detector
        |       Delta detection, refresh metadata, audit log
        |
        +--> QA / Provenance Gates
        |       Required fields, geometry, duplicate IDs, coverage tier, source lineage
        |
        +--> Supabase: public.structures
                Canonical structure database and source of truth
                    |
        +-----------+-----------+
        v           v           v
 Supabase API   SQL Server    Bulk Export
 REST/PostgREST enterprise    CSV / Parquet /
               sync           GeoJSON / WKT
```

The database is organized around a canonical core structure table plus optional extension tables/views:

- Core structure table: geometry, IDs, location, physical attributes, occupancy attributes, lineage, confidence, and update metadata.
- Planning extension: zoning, land use, parcel, year built, assessed value, and development context.
- Flood extension: flood zone, elevation, water proximity, exposure category, and event-specific monitoring fields.
- Oil and gas extension: wells, pipelines, facilities, buffers, asset proximity, and critical infrastructure context.
- Weather extension: wind, hail, tornado, storm exposure, roof/height classes, and severe-weather risk overlays.
- AI extension: suggest-only predictions, model confidence, model version, and features used.

The core table should remain useful on its own. Extensions should add domain context without changing the meaning of source-of-truth structure attributes.

## Attribute Rules

- Footprints are assigned to cities by representative point first, then largest boundary overlap; full building geometry is preserved.
- Overture footprints are primary. Microsoft footprints are retained only when representative-point and overlap checks show they are not duplicates.
- Missing units, stories, structure type, and occupant fields remain NULL unless a source or explicit labeled estimate fills them.
- Occupants use NSI population/employment/student fields first. Residential fallback uses `NumUnits * ACS B25010 average household size` and records the method.

## Data Sources

The pipeline records resolved source versions in the run manifest. Public inputs include Census TIGER/Line and Gazetteer files, Overture Maps STAC/GeoParquet, Microsoft dataset links, USACE NSI, Census ACS, and optional parcel services/files.

## AI Predictions

The `US_Structure_AI` branch adds an optional suggest-only AI layer. It predicts missing structure attributes but does not overwrite source-of-truth fields.

```bash
cp ai_inputs.example.py ai_inputs.py
python scripts/run_us_ai_pipeline.py
```

AI output columns include `PredictedStructureType`, `PredictedNumUnits`, `PredictedNumStories`, `PredictedOccupantCount`, `PredictionKind`, `PredictionModelName`, `PredictionModelVersion`, `PredictionConfidence`, and `PredictionFeaturesUsed`. V1 supports `suggest_only` mode only, so authoritative columns such as `StructureType`, `NumUnits`, `NumStories`, and `OccupantCount` remain unchanged.
