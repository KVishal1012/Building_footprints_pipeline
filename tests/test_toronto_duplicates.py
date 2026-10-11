"""Duplicate classification tests use synthetic data, not real building claims."""
import geopandas as gpd
from shapely import force_3d
from shapely.geometry import box

from scripts.audit_toronto_duplicates import audit_groups


def test_exact_repeats_mixed_conflicts_and_z_variants():
    a, b, c = box(0, 0, 1, 1), box(2, 0, 3, 1), box(4, 0, 5, 1)
    frame = gpd.GeoDataFrame({"AVG_HEIGHT": [5, 5, 10, 10, 11, 7, 7]},
        geometry=[a, a.reverse(), b, b, b, force_3d(c, z=0), force_3d(c, z=3)], crs=3857)
    members, groups, summary = audit_groups(frame)
    assert summary["duplicate_groups"] == 3
    assert summary["exact_repeat_excess_all_groups"] == 2
    assert set(groups.audit_class) == {"exact_record_repeats", "attribute_conflict_unresolved", "different_3d_geometry_unresolved"}
    assert members.loc[1, "repeat_of_fid"] == 0
    assert members.loc[3, "repeat_of_fid"] == 2
    assert summary["confirmed_building_component_groups"] == 0
    again, repeated, _ = audit_groups(frame.iloc[::-1])
    assert groups.equals(repeated)
    assert members.equals(again)


def test_empty_null_and_unique_are_not_duplicate_groups():
    frame = gpd.GeoDataFrame({"AVG_HEIGHT": [None, None, 3]}, geometry=[None, None, box(0, 0, 1, 1)], crs=3857)
    members, groups, summary = audit_groups(frame)
    assert members.empty and groups.empty and summary["accounting_reconciled"]
