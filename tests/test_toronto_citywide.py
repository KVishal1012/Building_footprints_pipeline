"""Synthetic coverage of partitioning, repairs, repeat lineage, and export."""
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon, GeometryCollection, Point, box

from scripts.build_toronto_citywide import prepare_citywide, build_citywide
from scripts.build_toronto_internal_sample import FIELDS


def source_fixture():
    """Return an exact pair, two conflicting variants, and repair/quarantine cases."""
    a, b = box(630000, 4835000, 630010, 4835010), box(630020, 4835020, 630030, 4835030)
    bad = Polygon([(630040,4835040),(630050,4835050),(630040,4835050),(630050,4835040),(630040,4835040)])
    frame = gpd.GeoDataFrame(geometry=[a, a, b, b, bad, GeometryCollection([Point(630060, 4835060)])], crs=26917).to_crs(3857)
    for field in sorted(FIELDS):
        frame[field] = "Site Plan" if field.endswith("SRC") else 5.0
    frame["MIN_HEIGHT"] = 0.0
    frame.loc[3, "AVG_HEIGHT"] = 8.0
    return frame


def test_partition_and_full_original_lineage():
    source = source_fixture()
    layers, lineage, log, report = prepare_citywide(source, "test")
    assert report["exact_repetitions_collapsed"] == 1
    assert report["partition_counts"] == {"structures": 2, "conflict_review": 2, "geometry_quarantine": 1}
    assert report["provenance_rows"] == 6 and report["accounting_reconciled"]
    assert lineage.loc[0, "StructureID"] == lineage.loc[1, "StructureID"]
    assert layers["conflict_review"].AVG_HEIGHT.tolist() == [5.0, 8.0]
    assert len(layers["geometry_before"]) == 2 and len(layers["geometry_after"]) == 1
    assert report["repaired"] == 1 and report["quarantined"] == 1
    assert layers["structures"].MIN_HEIGHT.isna().all()
    assert layers["structures"].MIN_HEIGHT_RAW.eq(0).all()
    again, lineage2, log2, report2 = prepare_citywide(source.iloc[::-1], "test")
    pd.testing.assert_frame_equal(lineage, lineage2)
    for name in layers:
        pd.testing.assert_frame_equal(layers[name], again[name])


def test_shapefile_end_to_end_and_empty_quarantine_layer(tmp_path):
    source = source_fixture().iloc[:5]
    path = tmp_path / "source.shp"
    source.to_file(path)
    report = build_citywide(path, tmp_path / "output")
    assert report["automated_verification"] == "passed"
    assert report["quarantined"] == 0
    assert (tmp_path / "output" / "geometry_changes.csv").exists()
    with pytest.raises(FileExistsError):
        build_citywide(path, tmp_path / "output")


def test_normalization_does_not_create_false_raw_repeat():
    source = source_fixture().iloc[:2].copy()
    source.loc[1, "MIN_HEIGHT"] = float("nan")
    layers, lineage, log, report = prepare_citywide(source, "test")
    assert report["exact_repetitions_collapsed"] == 0
    assert len(layers["conflict_review"]) == 2
