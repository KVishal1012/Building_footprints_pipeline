import geopandas as gpd
from shapely.geometry import box

from structures_pipeline.geometry import assign_footprints_to_place, dedupe_fallback_footprints


def test_assignment_preserves_full_cross_boundary_geometry():
    boundary = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")
    footprints = gpd.GeoDataFrame(
        {"StructureID": ["cross"]},
        geometry=[box(0.8, 0.2, 1.2, 0.6)],
        crs="EPSG:4326",
    )

    assigned = assign_footprints_to_place(footprints, boundary)

    assert len(assigned) == 1
    assert assigned.geometry.iloc[0].bounds == (0.8, 0.2, 1.2, 0.6)
    assert assigned.loc[0, "FootprintAssignmentMethod"] == "representative_point_within"


def test_microsoft_fallback_dedupes_by_overlap():
    primary = gpd.GeoDataFrame(
        {"StructureID": ["ovt_1"]},
        geometry=[box(0, 0, 1, 1)],
        crs="EPSG:4326",
    )
    fallback = gpd.GeoDataFrame(
        {"StructureID": ["msft_dup", "msft_new"]},
        geometry=[box(0.05, 0.05, 1.05, 1.05), box(2, 2, 3, 3)],
        crs="EPSG:4326",
    )

    deduped = dedupe_fallback_footprints(primary, fallback, overlap_ratio_threshold=0.10)

    assert deduped["StructureID"].tolist() == ["msft_new"]
