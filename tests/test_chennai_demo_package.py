import csv
import json
from pathlib import Path

import scripts.build_chennai_demo_package as chennai_package
from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS


def test_chennai_fixture_matches_canonical_header_shape():
    path = Path("examples/india_chennai_refresh_source.csv")
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows
    assert set(REQUIRED_OUTPUT_COLUMNS) - {"geometry"} <= set(rows[0])
    assert "geometry_wkt" in rows[0]
    assert {row["City"] for row in rows} == {"Chennai"}
    assert {row["State"] for row in rows} == {"Tamil Nadu"}
    assert {row["Country"] for row in rows} == {"India"}


def test_chennai_fixture_has_provenance_and_no_ai_authoritative_sources():
    rows = chennai_package.read_rows(Path("examples/india_chennai_refresh_source.csv"))
    source_columns = [
        "LoadSource",
        "RawDataSource",
        "FootprintSource",
        "StructureTypeSource",
        "NumStoriesSource",
        "NumUnitsSource",
        "OccupantCountSource",
    ]

    for row in rows:
        for column in source_columns:
            value = row[column].lower()
            assert value
            assert "ai" not in value
            assert "prediction" not in value
        assert row["data_refresh_timestamp"].endswith("+00:00")
        assert row["last_refreshed"].endswith("+00:00")


def test_chennai_package_builder_outputs_demo_package(tmp_path, monkeypatch):
    monkeypatch.setattr(chennai_package, "OUTPUT_DIR", tmp_path / "chennai_demo")

    chennai_package.main()

    expected = {
        "sample_structures.csv",
        "provenance_snapshot.csv",
        "coverage_gap_registry.csv",
        "release_manifest.json",
        "one_page_brief.md",
        "README.md",
    }
    assert expected == {path.name for path in chennai_package.OUTPUT_DIR.iterdir()}

    manifest = json.loads((chennai_package.OUTPUT_DIR / "release_manifest.json").read_text())
    assert manifest["quality_contract"]["release_gate_status"] == "passed"
    assert manifest["quality_contract"]["release_gate_blockers"] == []
    assert manifest["market"] == "Chennai, Tamil Nadu, India"
    assert "Coimbatore" in manifest["coverage"]["tamil_nadu_expansion_targets"]

    with (chennai_package.OUTPUT_DIR / "coverage_gap_registry.csv").open(newline="") as handle:
        coverage_rows = list(csv.DictReader(handle))
    assert coverage_rows[0]["City"] == "Chennai"
    assert coverage_rows[0]["State"] == "Tamil Nadu"

    with (chennai_package.OUTPUT_DIR / "provenance_snapshot.csv").open(newline="") as handle:
        provenance_rows = list(csv.DictReader(handle))
    for column in ("StructureTypeSource", "NumStoriesSource", "NumUnitsSource", "OccupantCountSource"):
        assert provenance_rows[0][column]
