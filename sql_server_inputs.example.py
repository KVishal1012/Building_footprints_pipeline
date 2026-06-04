from __future__ import annotations

from pathlib import Path

from structures_pipeline.sql_server import SqlServerPipelineSettings

# Target places to process. Add more dictionaries for more cities.
PLACE_SPECS = [
    {"city": "Houston", "state": "Texas"},
]

# Use STATE_FILTERS instead of PLACE_SPECS for whole-state runs.
STATE_FILTERS = None
ALL_US_CITIES = False
DATAFRAME_PREVIEW_ROWS = 10

# SQL Server connection and table inputs.
SQL_SERVER = {
    "server_name": "tcp:YOUR_SERVER,1433",
    "database_name": "YOUR_DATABASE",
    "username": "YOUR_USER",
    "password": "YOUR_PASSWORD",
    "trusted_connection": False,
    "driver": "ODBC Driver 18 for SQL Server",
    "encrypt": "yes",
    "trust_server_certificate": None,
}

# Baseline table used to build the buffered area of interest.
BASELINE = {
    "table": "dbo.AssetBaseline",
    "geometry_column": "Shape",
    "id_column": "AssetID",
    "where": "Status = 'Active'",
    "buffer_value": 250,
    "srid": 4326,
    "buffer_unit_to_meters": None,
}

# Optional authoritative structure table. Fill these columns when SQL Server
# should be the source of truth for attributes.
FOOTPRINTS = {
    "table": "dbo.AuthoritativeStructures",
    "raw_data_source": "nyc_pluto",
    "geometry_column": "Shape",
    "id_column": "StructureID",
    "structure_type_column": "StructureType",
    "units_column": "NumUnits",
    "stories_column": "NumStories",
    "height_column": "HeightM",
    "occupant_count_column": "OccupantCount",
    "where": None,
    "structure_type_source": "nyc_pluto_land_use",
    "units_source": "nyc_pluto_units_total",
    "stories_source": "nyc_pluto_num_floors",
    "height_source": "nyc_pluto_height_roof",
    "occupant_count_source": "nyc_pluto_occupancy",
}

# Final SQL Server table that receives the exported structures dataframe.
OUTPUT = {
    "table": "dbo.StructuresOutput",
    "if_exists": "append",
    "geometry_column": "geometry_wkt",
    "chunksize": 1000,
}

# Pipeline switches. Local JSON/parquet outputs are disabled by default.
PIPELINE_OVERRIDES = {
    "data_dir": Path("data"),
    "output_dir": Path("data/output"),
    "raw_dir": Path("data/raw"),
    "cache_dir": Path("cache"),
    "download_missing": True,
    "use_overture": True,
    "use_microsoft": True,
    "use_nsi": True,
    "use_census": True,
    "use_parcels": False,
    "write_local_outputs": False,
}


# Build the SQL Server settings consumed by the runner.
def get_settings() -> SqlServerPipelineSettings:
    """Build the SQL Server settings consumed by the runner."""
    return SqlServerPipelineSettings(
        server_name=SQL_SERVER["server_name"],
        database_name=SQL_SERVER["database_name"],
        output_table=OUTPUT["table"],
        baseline_table=BASELINE["table"],
        baseline_buffer_value=BASELINE["buffer_value"],
        footprint_table=FOOTPRINTS["table"],
        footprint_raw_data_source=FOOTPRINTS["raw_data_source"],
        footprint_geom_column=FOOTPRINTS["geometry_column"],
        footprint_id_column=FOOTPRINTS["id_column"],
        footprint_structure_type_column=FOOTPRINTS["structure_type_column"],
        footprint_units_column=FOOTPRINTS["units_column"],
        footprint_stories_column=FOOTPRINTS["stories_column"],
        footprint_height_column=FOOTPRINTS["height_column"],
        footprint_occupant_count_column=FOOTPRINTS["occupant_count_column"],
        footprint_where=FOOTPRINTS["where"],
        footprint_structure_type_source=FOOTPRINTS["structure_type_source"],
        footprint_units_source=FOOTPRINTS["units_source"],
        footprint_stories_source=FOOTPRINTS["stories_source"],
        footprint_height_source=FOOTPRINTS["height_source"],
        footprint_occupant_count_source=FOOTPRINTS["occupant_count_source"],
        baseline_srid=BASELINE["srid"],
        baseline_geom_column=BASELINE["geometry_column"],
        baseline_id_column=BASELINE["id_column"],
        baseline_where=BASELINE["where"],
        username=SQL_SERVER["username"],
        password=SQL_SERVER["password"],
        trusted_connection=SQL_SERVER["trusted_connection"],
        driver=SQL_SERVER["driver"],
        encrypt=SQL_SERVER["encrypt"],
        trust_server_certificate=SQL_SERVER["trust_server_certificate"],
        output_if_exists=OUTPUT["if_exists"],
        output_geometry_column=OUTPUT["geometry_column"],
        output_chunksize=OUTPUT["chunksize"],
        buffer_unit_to_meters=BASELINE["buffer_unit_to_meters"],
        write_local_outputs=PIPELINE_OVERRIDES["write_local_outputs"],
    )


# Return target selectors for run_pipeline.
def get_target() -> dict:
    """Return target selectors for run_pipeline."""
    return {
        "place_specs": PLACE_SPECS,
        "state_filters": STATE_FILTERS,
        "all_us_cities": ALL_US_CITIES,
    }


# Return non-SQL pipeline options.
def get_pipeline_overrides() -> dict:
    """Return non-SQL pipeline options."""
    return dict(PIPELINE_OVERRIDES)
