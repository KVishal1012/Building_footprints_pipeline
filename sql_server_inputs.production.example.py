from __future__ import annotations

from pathlib import Path

from structures_pipeline.sql_server import SqlServerPipelineSettings

# First pilot target. New York is the Census place; the baseline and footprint
# filters below constrain the area of interest to Manhattan.
PLACE_SPECS = [
    {"city": "New York", "state": "New York"},
]
STATE_FILTERS = None
ALL_US_CITIES = False
DATAFRAME_PREVIEW_ROWS = 20

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

BASELINE = {
    "table": "dbo.ManhattanBaseline",
    "geometry_column": "Shape",
    "id_column": "BaselineID",
    "where": "Borough = 'Manhattan'",
    "buffer_value": 250,
    "srid": 4326,
    # Buffer units:
    # - EPSG:4326 and EPSG:4269 are treated as meter-based SQL Server geography-style inputs.
    # - Common US-foot projected SRIDs are converted to meters before GeoPandas buffering.
    # - For custom projected SRIDs, set buffer_unit_to_meters manually.
    # - Example: if your baseline SRID is US survey feet, use 1200 / 3937.
    "buffer_unit_to_meters": None,
}

FOOTPRINTS = {
    "table": "dbo.NYC_PLUTO_Structures",
    "raw_data_source": "nyc_pluto",
    "geometry_column": "Shape",
    "srid": 4326,
    "optional": False,
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

OUTPUT = {
    "table": "dbo.StructuresOutput_Test",
    "if_exists": "replace",
    "geometry_column": "geometry_wkt",
    "chunksize": 1000,
    "preflight": True,
    "create_native_geometry": True,
    "native_geometry_column": "Shape",
    "native_geometry_srid": 4326,
}

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
    "derive_num_units": False,
    "derive_occupant_count": False,
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
        footprint_srid=FOOTPRINTS["srid"],
        footprint_optional=FOOTPRINTS["optional"],
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
        output_create_native_geometry=OUTPUT["create_native_geometry"],
        output_native_geometry_column=OUTPUT["native_geometry_column"],
        output_native_geometry_srid=OUTPUT["native_geometry_srid"],
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
