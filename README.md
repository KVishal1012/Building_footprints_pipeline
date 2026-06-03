# US Building Footprints Pipeline

Production-oriented Python pipeline for enriched structure polygons across US Census places in the 50 states plus DC.

The pipeline uses Census TIGER/Line place boundaries for reproducible city coverage, Overture Maps as the primary footprint source, Microsoft Global ML Building Footprints as de-duplicated fallback footprints, USACE NSI and ACS for attributes, optional parcel layers, and optional OSM enrichment for single-city/debug runs.

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
- `OUTPUT`
- `PIPELINE_OVERRIDES`

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

## Attribute Rules

- Footprints are assigned to cities by representative point first, then largest boundary overlap; full building geometry is preserved.
- Overture footprints are primary. Microsoft footprints are retained only when representative-point and overlap checks show they are not duplicates.
- Missing units, stories, structure type, and occupant fields remain NULL unless a source or explicit labeled estimate fills them.
- Occupants use NSI population/employment/student fields first. Residential fallback uses `NumUnits * ACS B25010 average household size` and records the method.

## Data Sources

The pipeline records resolved source versions in the run manifest. Public inputs include Census TIGER/Line and Gazetteer files, Overture Maps STAC/GeoParquet, Microsoft dataset links, USACE NSI, Census ACS, and optional parcel services/files.
