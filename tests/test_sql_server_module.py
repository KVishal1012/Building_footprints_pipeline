from urllib.parse import parse_qs, unquote_plus, urlparse

import pytest

from structures_pipeline.sql_server import (
    US_SURVEY_FOOT_TO_METERS,
    SqlServerPipelineSettings,
    buffer_meters_from_srid,
    build_sql_server_pipeline_config,
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
    assert config.sql_export["table"] == "dbo.StructuresOutput"
    assert config.return_dataframe is True
