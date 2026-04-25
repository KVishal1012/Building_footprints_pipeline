import sys
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from structure_pipeline import (  # noqa: E402
    MODULE_DIR,
    OUTPUT_COLUMNS,
    PipelineConfig,
    empty_gdf,
    finalize_attributes,
    load_city_parcels,
    merge_osm_footprints,
    normalize_state_name,
    validate_output_gdf,
)


def base_structures() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "StructureID": ["s1"],
            "FootprintSource": ["test"],
            "OvertureID": [pd.NA],
            "MicrosoftID": [pd.NA],
            "Confidence_MS": [pd.NA],
            "HasParts": [False],
        },
        geometry=[box(80.20, 13.00, 80.201, 13.001)],
        crs="EPSG:4326",
    )


class PipelineContractTests(unittest.TestCase):
    def test_india_defaults_and_state_aliases(self):
        config = PipelineConfig()

        self.assertEqual(config.country, "India")
        self.assertEqual(config.data_dir, MODULE_DIR / "data")
        self.assertEqual(config.output_dir, MODULE_DIR / "data/output")
        self.assertEqual(config.raw_dir, MODULE_DIR / "data/raw")
        self.assertEqual(config.cache_dir, MODULE_DIR / "cache")
        self.assertFalse(config.use_nsi)
        self.assertFalse(config.use_census)
        self.assertTrue(config.use_parcels)
        self.assertEqual(normalize_state_name("TN"), "Tamil Nadu")
        self.assertEqual(normalize_state_name("MH"), "Maharashtra")

    def test_empty_finalize_preserves_output_schema(self):
        out = finalize_attributes(
            empty_gdf(crs="EPSG:4326"),
            city="Chennai",
            state="TN",
            country="India",
            census_household_size=None,
            census_source=None,
        )

        self.assertEqual(list(out.columns), OUTPUT_COLUMNS)
        self.assertEqual(str(out.crs), "EPSG:4326")
        self.assertTrue(out.empty)

    def test_structure_only_schema_excludes_model_and_planning_columns(self):
        expected_columns = [
            "StructureID",
            "City",
            "State",
            "Country",
            "FootprintSource",
            "OvertureID",
            "MicrosoftID",
            "OSMID",
            "NSI_FD_ID",
            "NSI_RecordCount",
            "StructureType",
            "StructureTypeRaw",
            "StructureTypeSource",
            "BuildingName",
            "BuildingNameSource",
            "NumUnits",
            "NumUnitsSource",
            "NumStories",
            "NumStoriesSource",
            "HeightM",
            "HeightSource",
            "OccupantCount",
            "OccupantCountMethod",
            "NSI_Pop2AM",
            "NSI_Pop2PM",
            "NSI_EmpNum",
            "NSI_Students",
            "CBFIPS",
            "ParcelID",
            "ParcelAddress",
            "ParcelLandUse",
            "ParcelZoning",
            "ParcelOwner",
            "ParcelAssessedValue",
            "ParcelYearBuilt",
            "ParcelArea_m2",
            "ParcelSource",
            "ParcelMatchMethod",
            "FootprintArea_m2",
            "Confidence_MS",
            "HasParts",
            "CensusAvgHouseholdSize",
            "CensusSource",
            "geometry",
        ]

        self.assertEqual(OUTPUT_COLUMNS, expected_columns)

    def test_finalize_structure_fields(self):
        out = finalize_attributes(
            base_structures(),
            city="Chennai",
            state="TN",
            country="India",
            census_household_size=None,
            census_source=None,
        )

        self.assertEqual(list(out.columns), OUTPUT_COLUMNS)
        self.assertEqual(out.loc[0, "City"], "Chennai")
        self.assertEqual(out.loc[0, "State"], "Tamil Nadu")
        self.assertEqual(out.loc[0, "Country"], "India")
        self.assertEqual(out.loc[0, "FootprintSource"], "test")
        self.assertGreater(out.loc[0, "FootprintArea_m2"], 0)

    def test_strict_missing_parcel_source_raises(self):
        config = PipelineConfig(strict_sources=True)
        boundary = gpd.GeoDataFrame(
            geometry=[box(80.19, 12.99, 80.21, 13.01)], crs="EPSG:4326"
        )

        with self.assertRaises(RuntimeError):
            load_city_parcels(
                "chennai_tamil_nadu_india",
                "Chennai",
                "Tamil Nadu",
                boundary,
                config,
                parcel_source={"path": "missing_parcels.gpkg"},
            )

    def test_duplicate_structure_ids_fail_validation(self):
        gdf = gpd.GeoDataFrame(
            {"StructureID": ["s1", "s1"]},
            geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)],
            crs="EPSG:4326",
        )

        with self.assertRaises(ValueError):
            validate_output_gdf(gdf, "test", PipelineConfig())

    def test_merge_osm_footprints_uses_osm_when_base_is_empty(self):
        base = empty_gdf(crs="EPSG:4326")
        osm = gpd.GeoDataFrame(
            {
                "StructureID": ["osm_1"],
                "FootprintSource": ["osm"],
                "OSMID": ["1"],
            },
            geometry=[box(80.20, 13.00, 80.201, 13.001)],
            crs="EPSG:4326",
        )

        merged = merge_osm_footprints(base, osm, PipelineConfig())

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged.loc[0, "StructureID"], "osm_1")
        self.assertEqual(merged.loc[0, "FootprintSource"], "osm")

    def test_merge_osm_footprints_adds_unmatched_when_enabled(self):
        base = gpd.GeoDataFrame(
            {"StructureID": ["ovt_1"], "FootprintSource": ["overture"]},
            geometry=[box(80.20, 13.00, 80.201, 13.001)],
            crs="EPSG:4326",
        )
        osm = gpd.GeoDataFrame(
            {
                "StructureID": ["osm_overlap", "osm_unmatched"],
                "FootprintSource": ["osm", "osm"],
                "OSMID": ["10", "20"],
            },
            geometry=[
                box(80.2002, 13.0002, 80.2008, 13.0008),
                box(80.21, 13.01, 80.211, 13.011),
            ],
            crs="EPSG:4326",
        )

        merged = merge_osm_footprints(base, osm, PipelineConfig(add_osm_unmatched=True))

        self.assertEqual(len(merged), 2)
        self.assertIn("osm_unmatched", set(merged["StructureID"]))
        self.assertNotIn("osm_overlap", set(merged["StructureID"]))


if __name__ == "__main__":
    unittest.main()
