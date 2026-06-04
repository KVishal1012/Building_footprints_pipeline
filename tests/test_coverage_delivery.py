import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from structures_pipeline.config import PipelineConfig
from structures_pipeline.coverage import (
    apply_coverage_tiers,
    assign_coverage_tier,
    build_gap_registry,
    write_coverage_outputs,
)
from structures_pipeline.delivery import export_delivery_formats


def _frame():
    return gpd.GeoDataFrame(
        {
            "StructureID": ["s1", "s2"],
            "City": ["New York", "New York"],
            "State": ["New York", "New York"],
            "RawDataSource": ["nyc_pluto", "overture"],
            "FootprintSource": ["nyc_pluto", "overture"],
            "StructureType": ["residential", pd.NA],
            "NumUnits": [2, pd.NA],
            "NumStories": [4, 3],
            "OccupantCount": [5, pd.NA],
            "OccupantCountSource": ["nsi", pd.NA],
            "last_refreshed": ["2026-06-04", "2026-06-04"],
            "source_as_of": ["2026-Q2", "2026-06"],
        },
        geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)],
        crs="EPSG:4326",
    )


def test_assign_coverage_tier_uses_sources_and_overrides():
    frame = _frame()
    config = PipelineConfig()

    assert assign_coverage_tier("New York", "New York", frame, config) == "Tier 1"

    override = PipelineConfig(coverage_config={"tier_overrides": {"new york, new york": "Tier 2"}})
    assert assign_coverage_tier("New York", "New York", frame, override) == "Tier 2"


def test_build_gap_registry_computes_completeness():
    registry = build_gap_registry(_frame(), PipelineConfig())

    assert registry.loc[0, "CoverageTier"] == "Tier 1"
    assert registry.loc[0, "row_count"] == 2
    assert registry.loc[0, "structure_type_completeness"] == 0.5
    assert registry.loc[0, "num_stories_completeness"] == 1.0


def test_apply_coverage_tiers_sets_row_level_policy_field():
    tiered = apply_coverage_tiers(_frame(), PipelineConfig())

    assert tiered["CoverageTier"].tolist() == ["Tier 1", "Tier 1"]


def test_write_coverage_outputs(tmp_path):
    config = PipelineConfig(delivery_output_dir=tmp_path / "delivery")

    paths = write_coverage_outputs(_frame(), config)

    assert paths["gap_registry"].exists()
    assert paths["coverage_json"].exists()


def test_export_delivery_formats_writes_csv_parquet_geojson_and_postgis_shape(tmp_path):
    config = PipelineConfig(
        delivery_output_dir=tmp_path / "delivery",
        delivery_formats=["csv", "parquet", "geojson", "postgis"],
        postgis_export={"table": "public.structures"},
    )

    paths = export_delivery_formats(_frame(), config)

    assert paths["csv"].exists()
    assert paths["parquet"].exists()
    assert paths["geojson"].exists()
    assert paths["postgis"]["table"] == "public.structures"
    assert paths["postgis"]["rows_prepared"] == 2
