import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS
from structures_pipeline.validation import validate_output


def test_validate_output_accepts_required_schema():
    row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": "s1",
            "FootprintArea_m2": 10.0,
            "LoadSource": "overture",
            "RawDataSource": "overture",
            "FootprintSource": "overture",
            "OccupantCountSource": "acs",
            "created_at": "2026-06-04T00:00:00+00:00",
            "updated_at": "2026-06-04T00:00:00+00:00",
            "updated_by": "unit_test",
            "change_log": "[]",
            "last_refreshed": "2026-06-04T00:00:00+00:00",
            "source_as_of": "2026-06",
        }
    )
    gdf = gpd.GeoDataFrame([row], geometry=[box(0, 0, 0.001, 0.001)], crs="EPSG:4326")

    metrics = validate_output(gdf)

    assert metrics["row_count"] == 1
    assert metrics["acs_fallback_count"] == 1


def test_validate_output_rejects_ai_as_raw_source():
    row = {column: pd.NA for column in REQUIRED_OUTPUT_COLUMNS if column != "geometry"}
    row.update(
        {
            "StructureID": "s1",
            "FootprintArea_m2": 10.0,
            "LoadSource": "sql_server",
            "RawDataSource": "ml_inference",
            "FootprintSource": "overture",
            "created_at": "2026-06-04T00:00:00+00:00",
            "updated_at": "2026-06-04T00:00:00+00:00",
            "updated_by": "unit_test",
            "change_log": "[]",
            "last_refreshed": "2026-06-04T00:00:00+00:00",
            "source_as_of": "2026-06",
        }
    )
    gdf = gpd.GeoDataFrame([row], geometry=[box(0, 0, 0.001, 0.001)], crs="EPSG:4326")

    try:
        validate_output(gdf)
    except ValueError as exc:
        assert "RawDataSource" in str(exc)
    else:
        raise AssertionError("Expected RawDataSource validation failure")
