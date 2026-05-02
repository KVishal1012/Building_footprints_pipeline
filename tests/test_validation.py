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
            "FootprintSource": "overture",
            "OccupantCountSource": "acs",
        }
    )
    gdf = gpd.GeoDataFrame([row], geometry=[box(0, 0, 0.001, 0.001)], crs="EPSG:4326")

    metrics = validate_output(gdf)

    assert metrics["row_count"] == 1
    assert metrics["acs_fallback_count"] == 1
