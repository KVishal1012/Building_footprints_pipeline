import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from structures_pipeline.attributes import finalize_attributes, normalize_structure_type
from structures_pipeline.config import PipelineConfig


def test_normalize_structure_type_keeps_unknown_as_null():
    values = pd.Series(["Detached house", "COM1", "mixed_use", None])
    assert normalize_structure_type(values).tolist() == ["residential", "commercial", "mixed_use", pd.NA]


def test_finalize_attributes_uses_nsi_then_acs_for_occupants_when_enabled():
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
        config=PipelineConfig(derive_occupant_count=True),
    )

    assert final.loc[0, "OccupantCount"] == 5
    assert final.loc[0, "OccupantCountSource"] == "nsi"
    assert final.loc[1, "OccupantCount"] == 5
    assert final.loc[1, "OccupantCountSource"] == "acs"
    assert final.loc[1, "OccupantCountMethod"] == "num_units_x_acs_household_size"


def test_finalize_attributes_keeps_occupants_source_only_by_default():
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
            "Units_OSM": [pd.NA, 2],
            "FootprintAssignmentMethod": ["representative_point_within", "representative_point_within"],
            "FootprintAssignmentOverlapRatio": [pd.NA, pd.NA],
        },
        geometry=[box(0, 0, 0.001, 0.001), box(0.002, 0, 0.003, 0.001)],
        crs="EPSG:4326",
    )

    final = finalize_attributes(
        base,
        place=place,
        census_household_size=2.5,
        acs_source="ACS 2024 B25010_001E",
        overture_release="2026-04-15.0",
        census_year=2025,
        config=PipelineConfig(),
    )

    assert final["OccupantCount"].isna().all()
    assert final["OccupantCountSource"].isna().all()
    assert final["OccupantCountMethod"].isna().all()


def test_finalize_attributes_does_not_infer_single_family_units_by_default():
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
            "StructureID": ["a"],
            "FootprintSource": ["overture"],
            "OvertureID": ["oa"],
            "MicrosoftID": [pd.NA],
            "OvertureClass": ["detached house"],
            "NSI_ResUnits": [pd.NA],
            "Units_OSM": [pd.NA],
            "FootprintAssignmentMethod": ["representative_point_within"],
            "FootprintAssignmentOverlapRatio": [pd.NA],
        },
        geometry=[box(0, 0, 0.001, 0.001)],
        crs="EPSG:4326",
    )

    final = finalize_attributes(
        base,
        place=place,
        census_household_size=None,
        acs_source=None,
        overture_release="2026-04-15.0",
        census_year=2025,
        config=PipelineConfig(derive_num_units=False),
    )

    assert pd.isna(final.loc[0, "NumUnits"])
    assert pd.isna(final.loc[0, "NumUnitsSource"])


def test_finalize_attributes_can_infer_single_family_units_when_enabled():
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
            "StructureID": ["a"],
            "FootprintSource": ["overture"],
            "OvertureID": ["oa"],
            "MicrosoftID": [pd.NA],
            "OvertureClass": ["detached house"],
            "NSI_ResUnits": [pd.NA],
            "Units_OSM": [pd.NA],
            "FootprintAssignmentMethod": ["representative_point_within"],
            "FootprintAssignmentOverlapRatio": [pd.NA],
        },
        geometry=[box(0, 0, 0.001, 0.001)],
        crs="EPSG:4326",
    )

    final = finalize_attributes(
        base,
        place=place,
        census_household_size=None,
        acs_source=None,
        overture_release="2026-04-15.0",
        census_year=2025,
        config=PipelineConfig(derive_num_units=True),
    )

    assert final.loc[0, "NumUnits"] == 1
    assert final.loc[0, "NumUnitsSource"] == "inferred_single_family"


def test_finalize_attributes_prioritizes_authoritative_sql_attributes():
    place = pd.Series(
        {
            "PlaceGEOID": "3606100",
            "City": "Manhattan",
            "State": "New York",
            "StateFP": "36",
        }
    )
    base = gpd.GeoDataFrame(
        {
            "StructureID": ["sql_1"],
            "FootprintSource": ["sql_server_authoritative"],
            "OvertureID": [pd.NA],
            "MicrosoftID": [pd.NA],
            "SQLStructureType": ["mixed_use"],
            "SQLStructureTypeSource": ["nyc_pluto_land_use"],
            "OvertureClass": ["commercial"],
            "SQLUnits": [14],
            "SQLUnitsSource": ["nyc_pluto_units_total"],
            "Units_OSM": [pd.NA],
            "SQLStories": [22],
            "SQLStoriesSource": ["nyc_pluto_num_floors"],
            "Stories_OVT": [18],
            "SQLOccupantCount": [75],
            "SQLOccupantCountSource": ["nyc_pluto_occupancy"],
            "NSI_Pop2AM": [10],
            "NSI_Pop2PM": [12],
            "NSI_EmpNum": [pd.NA],
            "NSI_Students": [pd.NA],
            "FootprintAssignmentMethod": ["representative_point_within"],
            "FootprintAssignmentOverlapRatio": [pd.NA],
        },
        geometry=[box(0, 0, 0.001, 0.001)],
        crs="EPSG:4326",
    )

    final = finalize_attributes(
        base,
        place=place,
        census_household_size=2.5,
        acs_source="ACS test",
        overture_release="demo",
        census_year=2025,
        config=PipelineConfig(),
    )

    assert final.loc[0, "StructureType"] == "mixed_use"
    assert final.loc[0, "StructureTypeSource"] == "nyc_pluto_land_use"
    assert final.loc[0, "NumUnits"] == 14
    assert final.loc[0, "NumUnitsSource"] == "nyc_pluto_units_total"
    assert final.loc[0, "NumStories"] == 22
    assert final.loc[0, "NumStoriesSource"] == "nyc_pluto_num_floors"
    assert final.loc[0, "OccupantCount"] == 75
    assert final.loc[0, "OccupantCountSource"] == "nyc_pluto_occupancy"
    assert final.loc[0, "OccupantCountMethod"] == "sql_authoritative_count"
