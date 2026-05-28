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

A SQL table or query with a geometry column can be used as a footprint source. Store the SQLAlchemy connection string in an environment variable so credentials stay out of command history:

```bash
export STRUCTURES_SQL_URL='postgresql+psycopg2://user:password@host:5432/dbname'
python structure_pipeline.py \
  --place "Chicago, Illinois" \
  --sql-table public.building_footprints \
  --sql-geom-column geom \
  --sql-id-column building_id \
  --sql-structure-type-column use_type
```

For databases that do not return geometry as WKB/WKT directly, pass a query that aliases the geometry to `geom`, for example `ST_AsBinary(geom) AS geom`.

A SQL Server baseline table can also define the area of interest. The pipeline reads the baseline geometry, buffers it in meters, captures structures around that buffer, and writes `BaselineID`, `BaselineDistance_m`, and `BaselineBuffer_m` to the output:

```bash
export STRUCTURES_SQL_URL='mssql+pyodbc:///?odbc_connect=Driver%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BServer%3Dtcp%3Aserver.example.com%2C1433%3BDatabase%3Dgis%3BUID%3Duser%3BPWD%3Dpassword%3BEncrypt%3Dyes'
python structure_pipeline.py \
  --place "Houston, Texas" \
  --baseline-sql-table dbo.AssetBaseline \
  --baseline-sql-geom-column Shape \
  --baseline-sql-id-column AssetID \
  --baseline-buffer-meters 250 \
  --baseline-sql-where "Status = 'Active'" \
  --baseline-sqlserver-geometry-methods
```

Use `--no-download` to force cached local files only. Use `--use-osm` only for small/debug runs because OSM enrichment calls Overpass through OSMnx.

## Outputs

For each city, the pipeline writes:

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
