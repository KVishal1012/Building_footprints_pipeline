from types import SimpleNamespace
from urllib.parse import parse_qs, unquote_plus, urlparse

import pytest

from structures_pipeline.sql_server import (
    US_SURVEY_FOOT_TO_METERS,
    SqlServerPipelineSettings,
    buffer_meters_from_srid,
    build_sql_server_pipeline_config,
    run_sql_server_pipeline_from_inputs,
    sql_server_connection_url,
)


def test_buffer_meters_from_srid_keeps_geographic_buffers_in_meters():
    assert buffer_meters_from_srid(250, 4326) == 250


def test_buffer_meters_from_srid_converts_common_foot_srid():
    assert buffer_meters_from_srid(100, 2263) == pytest.approx(100 * US_SURVEY_FOOT_TO_METERS)


def test_buffer_meters_from_srid_allows_explicit_unit_override():
    assert buffer_meters_from_srid(100, 999999, unit_to_meters=0.5) == 50


def test_sql_server_connection_url_uses_server_database_and_credentials():
    settings = SqlServerPipelineSettings(
        server_name="tcp:server.example.com,1433",
        database_name="gis",
        output_table="dbo.StructuresOutput",
        baseline_table="dbo.AssetBaseline",
        baseline_buffer_value=250,
        username="user",
        password="secret",
    )

    url = sql_server_connection_url(settings)
    query = parse_qs(urlparse(url).query)
    odbc = unquote_plus(query["odbc_connect"][0])

    assert url.startswith("mssql+pyodbc:///?odbc_connect=")
    assert "Server=tcp:server.example.com,1433" in odbc
    assert "Database=gis" in odbc
    assert "UID=user" in odbc
    assert "PWD=secret" in odbc


def test_build_sql_server_pipeline_config_sets_baseline_and_export():
    settings = SqlServerPipelineSettings(
        server_name="localhost",
        database_name="gis",
        output_table="dbo.StructuresOutput",
        baseline_table="dbo.AssetBaseline",
        baseline_geom_column="Shape",
        baseline_id_column="AssetID",
        baseline_buffer_value=100,
        footprint_table="dbo.AuthoritativeStructures",
        footprint_raw_data_source="nyc_pluto",
        footprint_id_column="StructureID",
        footprint_structure_type_column="StructureType",
        footprint_units_column="NumUnits",
        footprint_stories_column="NumStories",
        footprint_occupant_count_column="OccupantCount",
        footprint_structure_type_source="nyc_pluto_land_use",
        footprint_units_source="nyc_pluto_units_total",
        footprint_stories_source="nyc_pluto_num_floors",
        footprint_occupant_count_source="nyc_pluto_occupancy",
        baseline_srid=2263,
        trusted_connection=True,
    )

    config = build_sql_server_pipeline_config(
        settings,
        output_dir="data/test_output",
        download_missing=False,
    )

    assert config.sql_baseline_source["table"] == "dbo.AssetBaseline"
    assert config.sql_baseline_source["geom_column"] == "Shape"
    assert config.sql_baseline_source["id_column"] == "AssetID"
    assert config.sql_baseline_source["buffer_meters"] == pytest.approx(100 * US_SURVEY_FOOT_TO_METERS)
    assert config.sql_baseline_source["sqlserver_geometry_methods"] is True
    assert config.sql_footprint_source["table"] == "dbo.AuthoritativeStructures"
    assert config.sql_footprint_source["load_source"] == "sql_server"
    assert config.sql_footprint_source["raw_data_source"] == "nyc_pluto"
    assert config.sql_footprint_source["id_column"] == "StructureID"
    assert config.sql_footprint_source["structure_type_column"] == "StructureType"
    assert config.sql_footprint_source["units_column"] == "NumUnits"
    assert config.sql_footprint_source["stories_column"] == "NumStories"
    assert config.sql_footprint_source["occupant_count_column"] == "OccupantCount"
    assert config.sql_footprint_source["structure_type_source"] == "nyc_pluto_land_use"
    assert config.sql_footprint_source["units_source"] == "nyc_pluto_units_total"
    assert config.sql_footprint_source["stories_source"] == "nyc_pluto_num_floors"
    assert config.sql_footprint_source["occupant_count_source"] == "nyc_pluto_occupancy"
    assert config.sql_export["table"] == "dbo.StructuresOutput"
    assert config.return_dataframe is True
    assert config.write_local_outputs is False


def test_run_sql_server_pipeline_from_inputs_uses_module_functions(monkeypatch):
    settings = SqlServerPipelineSettings(
        server_name="localhost",
        database_name="gis",
        output_table="dbo.StructuresOutput",
        baseline_table="dbo.AssetBaseline",
        baseline_buffer_value=100,
        trusted_connection=True,
    )
    input_module = SimpleNamespace(
        get_settings=lambda: settings,
        get_target=lambda: {
            "place_specs": [{"city": "Houston", "state": "Texas"}],
            "state_filters": None,
            "all_us_cities": False,
        },
        get_pipeline_overrides=lambda: {"download_missing": False},
    )
    captured = {}

    def fake_run_pipeline(*, place_specs, state_filters, all_us_cities, config):
        captured["place_specs"] = place_specs
        captured["state_filters"] = state_filters
        captured["all_us_cities"] = all_us_cities
        captured["config"] = config
        return {"dataframe": "df", "sql_export": {"rows_exported": 1}}

    monkeypatch.setattr("structures_pipeline.sql_server.run_pipeline", fake_run_pipeline)

    result = run_sql_server_pipeline_from_inputs(input_module)

    assert result["sql_export"]["rows_exported"] == 1
    assert captured["place_specs"] == [{"city": "Houston", "state": "Texas"}]
    assert captured["config"].download_missing is False
    assert captured["config"].sql_export["table"] == "dbo.StructuresOutput"


def test_run_sql_server_pipeline_from_inputs_requires_contract():
    with pytest.raises(ValueError, match="get_settings"):
        run_sql_server_pipeline_from_inputs(SimpleNamespace())
