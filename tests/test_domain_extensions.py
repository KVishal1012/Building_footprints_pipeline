import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from structures_pipeline.config import PipelineConfig
from structures_pipeline.extensions import (
    EXTENSION_SCHEMAS,
    build_extension_table,
    build_extension_tables,
    write_extension_tables,
)


def _frame():
    return gpd.GeoDataFrame(
        {"StructureID": ["s1", "s2"]},
        geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)],
        crs="EPSG:4326",
    )


def test_build_extension_table_keeps_core_join_key_and_schema():
    table = build_extension_table(_frame(), "flood")

    assert table.columns.tolist() == ["StructureID", *EXTENSION_SCHEMAS["flood"]]
    assert table["StructureID"].tolist() == ["s1", "s2"]
    assert pd.isna(table.loc[0, "FloodZone"])


def test_build_extension_tables_uses_configured_subset():
    config = PipelineConfig(domain_extensions=["weather", "urban_planning"])

    tables = build_extension_tables(_frame(), config)

    assert sorted(tables) == ["urban_planning", "weather"]
    assert "WeatherSource" in tables["weather"].columns
    assert "PlanningSource" in tables["urban_planning"].columns


def test_build_extension_tables_rejects_unknown_names():
    config = PipelineConfig(domain_extensions=["not_real"])

    try:
        build_extension_tables(_frame(), config)
    except ValueError as exc:
        assert "Unsupported domain extension" in str(exc)
    else:
        raise AssertionError("Expected unsupported extension validation failure")


def test_write_extension_tables_outputs_csv_files(tmp_path):
    config = PipelineConfig(
        delivery_output_dir=tmp_path / "delivery",
        domain_extensions=["flood", "oil_gas"],
    )

    paths = write_extension_tables(_frame(), config)

    assert sorted(paths) == ["flood", "oil_gas"]
    assert paths["flood"].exists()
    assert paths["oil_gas"].exists()
