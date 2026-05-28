import sqlite3

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box

from structures_pipeline.config import PipelineConfig
from structures_pipeline.sources import (
    attach_baseline_proximity,
    buffered_baseline_boundary,
    load_sql_footprints,
    read_sql_baseline_source,
    read_sql_geometry_source,
)


def test_read_sql_geometry_source_reads_wkt_geom_table(tmp_path):
    db_path = tmp_path / "footprints.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE footprints (building_id TEXT, use_type TEXT, stories INTEGER, geom TEXT)"
        )
        conn.execute(
            "INSERT INTO footprints VALUES (?, ?, ?, ?)",
            ("b1", "residential", 2, "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))"),
        )

    config = PipelineConfig(
        sql_footprint_source={
            "connection": f"sqlite:///{db_path}",
            "table": "footprints",
            "geom_column": "geom",
        }
    )

    gdf = read_sql_geometry_source(config.sql_footprint_source, config)

    assert list(gdf["building_id"]) == ["b1"]
    assert gdf.crs.to_string() == "EPSG:4326"
    assert gdf.geometry.iloc[0].area == 1


def test_load_sql_footprints_standardizes_and_assigns_to_place(tmp_path):
    db_path = tmp_path / "footprints.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE footprints (building_id TEXT, use_type TEXT, height_m REAL, stories INTEGER, geom TEXT)"
        )
        conn.executemany(
            "INSERT INTO footprints VALUES (?, ?, ?, ?, ?)",
            [
                ("inside", "house", 6.0, 2, "POLYGON ((0.1 0.1, 0.1 0.2, 0.2 0.2, 0.2 0.1, 0.1 0.1))"),
                ("outside", "warehouse", 9.0, 3, "POLYGON ((2 2, 2 3, 3 3, 3 2, 2 2))"),
            ],
        )
    place = pd.Series(
        {
            "PlaceGEOID": "1714000",
            "City": "Chicago",
            "State": "Illinois",
            "StateFP": "17",
        }
    )
    boundary = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")
    config = PipelineConfig(
        sql_footprint_source={
            "connection": f"sqlite:///{db_path}",
            "table": "footprints",
            "geom_column": "geom",
            "id_column": "building_id",
            "structure_type_column": "use_type",
            "height_column": "height_m",
            "stories_column": "stories",
            "source_name": "city_sql",
        }
    )

    footprints = load_sql_footprints(place, boundary, config)

    assert len(footprints) == 1
    assert footprints.iloc[0]["StructureID"].endswith("inside")
    assert footprints.iloc[0]["FootprintSource"] == "city_sql"
    assert footprints.iloc[0]["SQLStructureType"] == "house"
    assert footprints.iloc[0]["SQLHeight"] == 6.0
    assert footprints.iloc[0]["SQLStories"] == 2


def test_sql_baseline_source_buffers_and_tags_nearest_structure(tmp_path):
    db_path = tmp_path / "baseline.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE baseline (asset_id TEXT, geom TEXT)")
        conn.execute("INSERT INTO baseline VALUES (?, ?)", ("asset-1", "POINT (0.15 0.15)"))

    config = PipelineConfig(
        sql_baseline_source={
            "connection": f"sqlite:///{db_path}",
            "table": "baseline",
            "geom_column": "geom",
            "id_column": "asset_id",
            "buffer_meters": 100,
        }
    )

    baseline = read_sql_baseline_source(config.sql_baseline_source, config)
    boundary = buffered_baseline_boundary(baseline, 100)
    structures = gpd.GeoDataFrame(
        {"StructureID": ["s1"]},
        geometry=[box(0.149, 0.149, 0.151, 0.151)],
        crs="EPSG:4326",
    )

    tagged = attach_baseline_proximity(structures, baseline, 100)

    assert baseline.iloc[0]["BaselineID"] == "asset-1"
    assert len(boundary) == 1
    assert boundary.geometry.iloc[0].contains(Point(0.15, 0.15))
    assert tagged.iloc[0]["BaselineID"] == "asset-1"
    assert tagged.iloc[0]["BaselineBuffer_m"] == 100
    assert tagged.iloc[0]["BaselineDistance_m"] >= 0
