from __future__ import annotations

from pathlib import Path

from structures_pipeline.sql_server import SqlServerPipelineSettings

# First production pilot target.
PLACE_SPECS = [
    {"city": "New York", "state": "New York"},
]
STATE_FILTERS = None
ALL_US_CITIES = False
DATAFRAME_PREVIEW_ROWS = 25

# SQL Server connection and table inputs.
# Copy this file to sql_server_inputs.py and replace these values locally.
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

# Baseline table used to define the buffered area of interest. For a Manhattan
# pilot, this can be an asset, parcel, district, corridor, or study-area table.
BASELINE = {
    "table": "dbo.ManhattanBaseline",
    "geometry_column": "Shape",
    "id_column": "BaselineID",
    "where": "Borough = 'Manhattan'",
    "buffer_value": 250,
    "srid": 4326,
    "buffer_unit_to_meters": None,
}

# Authoritative structure/footprint table. The raw_data_source and per-attribute
# source labels should name the real upstream authority, not SQL Server itself.
FOOTPRINTS = {
    "table": "dbo.NYC_PLUTO_Structures",
    "raw_data_source": "nyc_pluto",
    "geometry_column": "Shape",
    "id_column": "BBL",
    "structure_type_column": "LandUse",
    "units_column": "UnitsTotal",
    "stories_column": "NumFloors",
    "height_column": None,
    "occupant_count_column": None,
    "where": "Borough = 'MN'",
    "structure_type_source": "nyc_pluto_land_use",
    "units_source": "nyc_pluto_units_total",
    "stories_source": "nyc_pluto_num_floors",
    "height_source": None,
    "occupant_count_source": None,
}

# Final SQL Server table that receives the approved final structures dataframe.
OUTPUT = {
    "table": "dbo.StructureIntelligence_Manhattan",
    "if_exists": "append",
    "geometry_column": "geometry_wkt",
    "chunksize": 1000,
    "preflight": True,
}

# Keep the SQL Server path table-only by default. Overture/NSI/ACS remain useful
# fallback/enrichment sources where authoritative SQL fields are null.
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
        preflight=OUTPUT["preflight"],
        buffer_unit_to_meters=BASELINE["buffer_unit_to_meters"],
        write_local_outputs=PIPELINE_OVERRIDES["write_local_outputs"],
    )


def get_target() -> dict:
    """Return target selectors for run_pipeline."""
    return {
        "place_specs": PLACE_SPECS,
        "state_filters": STATE_FILTERS,
        "all_us_cities": ALL_US_CITIES,
    }


def get_pipeline_overrides() -> dict:
    """Return non-SQL pipeline options."""
    return dict(PIPELINE_OVERRIDES)
