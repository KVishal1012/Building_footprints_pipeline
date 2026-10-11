"""Synthetic fixtures test processing only; they are not Toronto sales samples."""
import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon, Point, box
from shapely import force_3d

from structures_pipeline.toronto import build_toronto_pack, checksum, prepare_buildings


@pytest.fixture
def inputs(tmp_path):
    boundary = gpd.GeoDataFrame(geometry=[box(630000, 4835000, 630100, 4835100)], crs=26917)
    source = gpd.GeoDataFrame({"id": ["cross", "inside", "outside"]}, geometry=[
        box(630090, 4835010, 630110, 4835020), box(630010, 4835010, 630020, 4835020),
        box(631000, 4835000, 631010, 4835010)], crs=26917)
    source_path, boundary_path = tmp_path / "source.gpkg", tmp_path / "area.gpkg"
    source.to_file(source_path)
    boundary.to_file(boundary_path)
    manifest = {"source_name": "synthetic_test_only", "source_url": "https://example.org/test",
                "license_url": "https://example.org/test-license", "attribution": "Synthetic test fixture",
                "retrieved_at": "2026-09-16T00:00:00+00:00", "source_as_of": None,
                "source_sha256": checksum(source_path), "id_column": "id", "reviewed_by": "test",
                "reviewed_at": "2026-09-16T00:00:00+00:00", "review_notes": "Test only",
                "commercial_use_review": "approved", "suitability_review": "approved",
                "identity_review": "one_record_per_building", "limitations": ["Synthetic; not real buildings."]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return source, boundary, manifest, source_path, boundary_path, manifest_path


def test_full_footprints_area_identity_and_accounting(inputs):
    source, boundary, manifest, *_ = inputs
    result, rejected, report = prepare_buildings(source, boundary, manifest)
    assert result.set_index("SourceRecordID").loc["cross", "FootprintArea_m2"] == pytest.approx(200)
    assert result.BoundaryCrossing.sum() == 1
    assert report["outside_study_area"] == 1
    assert report["accounting_reconciled"] and rejected.empty
    assert result.NumStories.isna().all() and result.PlaceGEOID.isna().all()
    rerun, _, _ = prepare_buildings(source.iloc[::-1], boundary, manifest)
    pd.testing.assert_frame_equal(result, rerun)


def test_duplicate_groups_missing_ids_and_bad_geometry(inputs):
    source, boundary, manifest, *_ = inputs
    source = gpd.GeoDataFrame({"id": ["a", "b", "dup", "dup", None, "point", "good"]},
        geometry=[source.geometry[0], source.geometry[0], source.geometry[1], source.geometry[1],
                  None, Point(630010, 4835010), box(630030, 4835030, 630040, 4835040)], crs=26917)
    result, rejected, report = prepare_buildings(source, boundary, manifest)
    assert len(result) == 1 and len(rejected) == 6
    assert set(rejected.reason) == {"duplicate_geometry", "duplicate_source_id", "missing_source_id", "non_polygon_geometry"}
    assert report["accounting_reconciled"]


def test_invalid_polygon_repair_is_disclosed(inputs):
    source, boundary, manifest, *_ = inputs
    source = source.iloc[:1].copy()
    source.geometry = [Polygon([(630010,4835010),(630020,4835020),(630010,4835020),(630020,4835010),(630010,4835010)])]
    result, _, report = prepare_buildings(source, boundary, manifest)
    assert result.geometry.is_valid.all() and report["repaired_output_rows"] == 1


@pytest.mark.parametrize("case", ["missing_crs", "empty_area", "invalid_area", "too_large", "outside_toronto", "no_matches"])
def test_fail_closed_inputs(inputs, case):
    source, boundary, manifest, *_ = inputs
    if case == "missing_crs":
        source = source.set_crs(None, allow_override=True)
    elif case == "empty_area":
        boundary = boundary.iloc[:0]
    elif case == "invalid_area":
        boundary.geometry = [Point(630010, 4835010)]
    elif case == "too_large":
        boundary.geometry = [box(630000, 4835000, 633000, 4838000)]
    elif case == "outside_toronto":
        boundary = gpd.GeoDataFrame(geometry=[box(0, 0, .001, .001)], crs=4326)
    else:
        source = source.iloc[2:]
    with pytest.raises(ValueError):
        prepare_buildings(source, boundary, manifest)


def test_feature_limit(inputs):
    source, boundary, manifest, *_ = inputs
    many = gpd.GeoDataFrame({"id": [str(i) for i in range(5001)]},
                            geometry=[source.geometry[0]] * 5001, crs=26917)
    with pytest.raises(ValueError, match="5,000"):
        prepare_buildings(many, boundary, manifest)


def test_package_roundtrip_checksums_and_no_overwrite(inputs, tmp_path):
    _, _, _, source, boundary, manifest = inputs
    output = tmp_path / "release"
    release = build_toronto_pack(source, manifest, boundary, output)
    assert release["quality_contract"]["release_gates"]["status"] == "pending"
    assert release["freshness"]["source_as_of"] is None
    for name, digest in release["delivery"]["files"].items():
        assert checksum(output / name) == digest
    table = pd.read_csv(output / "attributes.csv")
    geo = gpd.read_file(output / "buildings.gpkg")
    assert table.StructureID.tolist() == geo.StructureID.tolist()
    assert geo.crs.to_epsg() == 4326
    with pytest.raises(FileExistsError):
        build_toronto_pack(source, manifest, boundary, output)
    again = build_toronto_pack(source, manifest, boundary, tmp_path / "second")
    assert release["release_id"] == again["release_id"]


@pytest.mark.parametrize("field,value", [("commercial_use_review", "pending"), ("suitability_review", "blocked"),
    ("source_sha256", "incorrect"), ("identity_review", "unknown"), ("reviewed_by", ""), ("limitations", []),
    ("retrieved_at", "2026-09-16")])
def test_manifest_gates_publish_nothing(inputs, tmp_path, field, value):
    _, _, contents, source, boundary, manifest = inputs
    contents[field] = value
    manifest.write_text(json.dumps(contents))
    with pytest.raises(ValueError):
        build_toronto_pack(source, manifest, boundary, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()


def test_flattening_is_explicit(inputs):
    source, boundary, manifest, *_ = inputs
    source.geometry = source.geometry.map(lambda g: force_3d(g, z=12))
    result, _, report = prepare_buildings(source, boundary, manifest)
    assert report["flattened_output_rows"] == 2
    assert not result.geometry.has_z.any()


def test_min_height_zero_is_missing_without_losing_source(inputs):
    source, boundary, manifest, *_ = inputs
    source["MIN_HEIGHT"] = [0.0, 2.5, None]
    result, _, report = prepare_buildings(source, boundary, manifest)
    rows = result.set_index("SourceRecordID")
    assert pd.isna(rows.loc["cross", "MIN_HEIGHT"])
    assert rows.loc["cross", "MIN_HEIGHT_RAW"] == 0.0
    assert rows.loc["cross", "MinHeightStatus"] == "zero_assumed_missing"
    assert rows.loc["inside", "MIN_HEIGHT"] == 2.5
    assert report["min_height_zero_assumed_missing"] == 1
    source.loc[0, "MIN_HEIGHT"] = None
    result, _, _ = prepare_buildings(source, boundary, manifest)
    assert result.set_index("SourceRecordID").loc["cross", "MinHeightStatus"] == "source_missing"


def test_failed_write_leaves_no_release(inputs, tmp_path, monkeypatch):
    _, _, _, source, boundary, manifest = inputs
    def fail(*args, **kwargs):
        raise OSError("Simulated disk error")
    monkeypatch.setattr(gpd.GeoDataFrame, "to_file", fail)
    with pytest.raises(OSError, match="disk error"):
        build_toronto_pack(source, manifest, boundary, tmp_path / "release")
    assert not (tmp_path / "release").exists()
    assert not list(tmp_path.glob(".toronto-*"))


def test_internal_sample_does_not_approve_customer_release(inputs, tmp_path):
    _, _, contents, source, boundary, manifest = inputs
    contents.update(commercial_use_review="pending", suitability_review="context_only", identity_review="snapshot_records_only")
    manifest.write_text(json.dumps(contents))
    release = build_toronto_pack(source, manifest, boundary, tmp_path / "internal", internal_only=True)
    assert release["status"] == "internal_only_not_for_customer_delivery"
    assert "commercial_use_review" in release["quality_contract"]["release_gates"]["blockers"]
    with pytest.raises(ValueError, match="approved"):
        build_toronto_pack(source, manifest, boundary, tmp_path / "customer")


def test_shapefile_adapter_preserves_fields_and_snapshot_ids(inputs, tmp_path):
    from scripts.build_toronto_internal_sample import build_sample, FIELDS
    source = inputs[0].iloc[:2].copy().to_crs(3857)
    for column in FIELDS:
        source[column] = "Site Plan" if column.endswith("SRC") else 3.1
    source["MIN_HEIGHT"] = 0.0
    path = tmp_path / "massing.shp"
    source.drop(columns="id").to_file(path)
    centre = source.to_crs(4326).geometry.iloc[0].representative_point()
    output = tmp_path / "sample"
    build_sample(path, output, centre.x, centre.y)
    result = gpd.read_file(output / "package" / "buildings.gpkg")
    assert result.AVG_HEIGHT.eq(3.1).all()
    assert result.HEIGHT_SRC.eq("Site Plan").all()
    assert result.MIN_HEIGHT.isna().all() and result.MIN_HEIGHT_RAW.eq(0).all()
    build_sample(path, tmp_path / "again", centre.x, centre.y)
    again = gpd.read_file(tmp_path / "again" / "package" / "buildings.gpkg")
    assert result.StructureID.tolist() == again.StructureID.tolist()
    path.with_suffix(".prj").unlink()
    with pytest.raises(ValueError, match="Missing required"):
        build_sample(path, tmp_path / "missing", centre.x, centre.y)
