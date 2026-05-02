import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from structures_pipeline.attributes import finalize_attributes, normalize_structure_type


def test_normalize_structure_type_keeps_unknown_as_null():
    values = pd.Series(["Detached house", "COM1", None])
    assert normalize_structure_type(values).tolist() == ["residential", "commercial", pd.NA]


def test_finalize_attributes_uses_nsi_then_acs_for_occupants():
    place = pd.Series(
        {
            "PlaceGEOID": "1714000",
            "City": "Chicago",
            "State": "Illinois",
            "StateFP": "17",
        }
    )
    base = gpd.GeoDataFrame(
        {
            "StructureID": ["a", "b"],
            "FootprintSource": ["overture", "overture"],
            "OvertureID": ["oa", "ob"],
            "MicrosoftID": [pd.NA, pd.NA],
            "OvertureClass": ["residential", "residential"],
            "NSI_ResUnits": [pd.NA, pd.NA],
            "NSI_Pop2AM": [5, pd.NA],
            "NSI_Pop2PM": [4, pd.NA],
            "NSI_EmpNum": [pd.NA, pd.NA],
            "NSI_Students": [pd.NA, pd.NA],
            "FootprintAssignmentMethod": ["representative_point_within", "representative_point_within"],
            "FootprintAssignmentOverlapRatio": [pd.NA, pd.NA],
        },
        geometry=[box(0, 0, 0.001, 0.001), box(0.002, 0, 0.003, 0.001)],
        crs="EPSG:4326",
    )
    base["Units_OSM"] = [pd.NA, 2]

    final = finalize_attributes(
        base,
        place=place,
        census_household_size=2.5,
        acs_source="ACS 2024 B25010_001E",
        overture_release="2026-04-15.0",
        census_year=2025,
    )

    assert final.loc[0, "OccupantCount"] == 5
    assert final.loc[0, "OccupantCountSource"] == "nsi"
    assert final.loc[1, "OccupantCount"] == 5
    assert final.loc[1, "OccupantCountSource"] == "acs"
    assert final.loc[1, "OccupantCountMethod"] == "num_units_x_acs_household_size"
