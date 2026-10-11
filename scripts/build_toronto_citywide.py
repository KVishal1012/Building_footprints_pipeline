"""Produce an internal citywide GeoPackage with exact-repeat lineage and review layers."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely import force_2d, is_valid_reason, make_valid, normalize, to_wkb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.audit_toronto_duplicates import audit_groups
from scripts.build_toronto_internal_sample import FIELDS, source_inventory
from structures_pipeline.toronto import checksum

LOG = logging.getLogger(__name__)
SCHEMA = "toronto-citywide-internal-1"


def prepare_citywide(frame: gpd.GeoDataFrame, fingerprint: str) -> tuple[dict, pd.DataFrame, pd.DataFrame, dict]:
    """Collapse only identical raw records, then repair with complete lineage.

    Raw geometry and all raw attributes determine repeats before minimum-height
    normalization or repair. Conflicting variants remain distinct. Geometry
    collections resulting from repair are quarantined intact, not stripped.
    """
    if frame.crs is None or frame.crs.to_epsg() != 3857:
        raise ValueError("Expected explicitly declared EPSG:3857 source.")
    if not FIELDS.issubset(frame.columns):
        raise ValueError(f"Missing fields: {sorted(FIELDS-set(frame.columns))}")
    if frame.empty or not frame.index.is_unique or not pd.api.types.is_integer_dtype(frame.index.dtype):
        raise ValueError("Require nonempty source with unique integer OGR FIDs.")
    members, groups, audit = audit_groups(frame)
    representative = pd.Series(frame.index.to_numpy(copy=True), index=frame.index.copy(), dtype="int64", copy=True)
    repeated = members.repeat_of_fid.dropna().astype("int64")
    representative.loc[repeated.index] = repeated
    representatives = sorted(representative.unique())
    kept = frame.loc[representatives].copy()
    kept["representative_fid"] = kept.index
    id_map = pd.Series({fid: "toronto_" + hashlib.sha256(json.dumps(
        ["toronto_3d_massing_2025", f"{fingerprint}:{fid}"], ensure_ascii=False).encode()).hexdigest()
        for fid in representatives})
    kept["StructureID"] = id_map
    kept["SourceRecordID"] = [f"{fingerprint}:{fid}" for fid in kept.index]
    kept["source_record_count"] = representative.value_counts().reindex(kept.index).astype(int)
    kept["duplicate_group"] = members.duplicate_group.reindex(kept.index).fillna("")
    kept["DuplicateStatus"] = members.audit_class.reindex(kept.index).fillna("not_exact_xy_duplicate")
    kept["GeometryStatus"] = "valid_source"
    kept["ZRemoved"] = kept.geometry.has_z
    raw_min = pd.to_numeric(kept.MIN_HEIGHT, errors="raise")
    if not raw_min.dropna().map(math.isfinite).all():
        raise ValueError("Non-finite minimum height.")
    kept["MIN_HEIGHT_RAW"] = raw_min
    kept["MIN_HEIGHT"] = raw_min.mask(raw_min.eq(0))
    kept["MinHeightStatus"] = "source_value_unverified"
    kept.loc[raw_min.eq(0), "MinHeightStatus"] = "zero_assumed_missing"
    kept.loc[raw_min.isna(), "MinHeightStatus"] = "source_missing"
    kept["MinHeightMethod"] = "zero_to_null_provisional_project_rule"
    kept["City"], kept["State"], kept["Country"] = "Toronto", "Ontario", "Canada"
    kept["FootprintSource"] = "toronto_3d_massing_2025"
    kept["FootprintAreaMethod"] = "prepared_full_footprint_epsg_26917"
    kept["IdentityStatus"] = "snapshot_record_not_verified_building"
    kept.geometry = force_2d(kept.geometry.array)
    repair_log = []
    bad_ids = kept.index[kept.geometry.isna() | kept.geometry.is_empty | ~kept.geometry.is_valid |
                         ~kept.geom_type.isin(["Polygon", "MultiPolygon"])]
    before = kept.loc[bad_ids].copy()
    before.geometry = frame.loc[bad_ids].geometry
    for fid in bad_ids:
        original = kept.loc[fid, "geometry"]
        reason = str(is_valid_reason(original))
        fixed = make_valid(original) if original is not None and not original.is_empty else original
        accepted = (fixed is not None and not fixed.is_empty and fixed.is_valid and
                    fixed.geom_type in {"Polygon", "MultiPolygon"})
        status = "repaired_make_valid" if accepted else "quarantined_non_polygon_or_empty"
        kept.loc[fid, "GeometryStatus"] = status
        if accepted:
            kept.loc[fid, "geometry"] = fixed
        pair = gpd.GeoSeries([original, fixed], crs=3857).to_crs(26917)
        area_before = float(pair.iloc[0].area) if original is not None else None
        area_after = float(pair.iloc[1].area) if fixed is not None else None
        repair_log.append({"representative_fid": int(fid), "StructureID": id_map[fid],
            "reason": reason, "method": "shapely.make_valid on 2D source CRS", "outcome": status,
            "result_type": fixed.geom_type if fixed is not None else None,
            "area_before_m2": area_before, "area_after_m2": area_after,
            "area_delta_m2": area_after-area_before if area_before is not None and area_after is not None else None,
            "original_wkb_hex": original.wkb_hex if original is not None else None,
            "attempted_result_wkb_hex": fixed.wkb_hex if fixed is not None else None})
    quarantine = kept.GeometryStatus.str.startswith("quarantined")
    conflict = kept.DuplicateStatus.isin(["attribute_conflict_unresolved", "different_3d_geometry_unresolved"])
    kept["OutputLayer"] = "structures"
    kept.loc[conflict, "OutputLayer"] = "conflict_review"
    kept.loc[quarantine, "OutputLayer"] = "geometry_quarantine"
    # Invalid quarantined polygons have no asserted footprint area.
    kept["FootprintArea_m2"] = float("nan")
    kept.loc[~quarantine, "FootprintArea_m2"] = kept.loc[~quarantine].to_crs(26917).area
    if not kept.loc[~quarantine, "FootprintArea_m2"].gt(0).all():
        raise ValueError("Nonpositive prepared polygon area.")
    geometry_keys = pd.Series(to_wkb(normalize(kept.loc[~quarantine].geometry.array)), index=kept.index[~quarantine])
    kept["PostRepairCoincidentXY"] = geometry_keys.duplicated(keep=False).reindex(kept.index, fill_value=False)
    # Coincidence created by repair is disclosed, never used for another collapse.
    lineage = pd.DataFrame({"source_fid": frame.index, "representative_fid": representative.values})
    lineage["SourceRecordID"] = [f"{fingerprint}:{fid}" for fid in frame.index]
    lineage["StructureID"] = representative.map(id_map).values
    lineage["action"] = ["exact_repeat_collapsed" if fid != rep else "retained_variant"
                          for fid, rep in zip(frame.index, representative)]
    lineage["OutputLayer"] = representative.map(kept.OutputLayer).values
    lineage["GeometryStatus"] = representative.map(kept.GeometryStatus).values
    lineage = lineage.sort_values("source_fid").reset_index(drop=True)
    layers = {name: kept[kept.OutputLayer.eq(name)].sort_index().to_crs(4326).reset_index(drop=True)
              for name in ("structures", "conflict_review", "geometry_quarantine")}
    before["GeometryStatus"] = kept.loc[bad_ids, "GeometryStatus"]
    before["OutputLayer"] = kept.loc[bad_ids, "OutputLayer"]
    layers["geometry_before"] = before.to_crs(4326).reset_index(drop=True)
    layers["geometry_after"] = kept.loc[bad_ids[~quarantine.loc[bad_ids]]].to_crs(4326).reset_index(drop=True)
    log = pd.DataFrame(repair_log, columns=list(repair_log[0]) if repair_log else ["representative_fid", "StructureID", "outcome"])
    counts = {name: len(layers[name]) for name in ("structures", "conflict_review", "geometry_quarantine")}
    report = {"input_records": len(frame), "exact_repetitions_collapsed": len(repeated),
        "distinct_variants": len(kept), "partition_counts": counts,
        "conflict_groups": int(kept.loc[conflict, "duplicate_group"].nunique()),
        "conflict_distinct_variants": int(conflict.sum()), "geometry_cases": len(bad_ids),
        "repaired": int(kept.GeometryStatus.eq("repaired_make_valid").sum()), "quarantined": int(quarantine.sum()),
        "provenance_rows": len(lineage), "min_height_zero_assumed_missing": int(raw_min.eq(0).sum()),
        "post_repair_coincident_xy_records": int(kept.PostRepairCoincidentXY.sum()),
        "accounting_reconciled": len(frame) == len(repeated) + sum(counts.values()),
        "review_layer_note": "geometry_before/after duplicate review views; do not add them to partition counts",
        "duplicate_audit": audit, "qgis_review": "pending", "commercial_status": "internal_only_not_for_customer_delivery"}
    if not report["accounting_reconciled"] or not lineage.SourceRecordID.is_unique or not kept.StructureID.is_unique:
        raise ValueError("Identity/accounting reconciliation failed.")
    return layers, lineage, log, report


def verify_gpkg(path: Path, expected: dict, lineage: pd.DataFrame) -> None:
    """Read every layer back and check schema, values, geometry, and lineage SQL."""
    for name, frame in expected.items():
        actual = gpd.read_file(path, layer=name)
        if len(actual) != len(frame) or actual.crs.to_epsg() != 4326:
            raise ValueError(f"Layer count/CRS mismatch: {name}")
        pd.testing.assert_frame_equal(actual.drop(columns="geometry"), frame.drop(columns="geometry"), check_dtype=False)
        valid_rows = frame.geometry.notna()
        if not actual.loc[valid_rows].geometry.geom_equals_exact(frame.loc[valid_rows].geometry, 1e-12).all():
            raise ValueError(f"Geometry roundtrip mismatch: {name}")
        if name not in {"geometry_before", "geometry_quarantine"} and not actual.geometry.is_valid.all():
            raise ValueError(f"Invalid prepared geometry: {name}")
    with sqlite3.connect(path) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity failure.")
        restored = pd.read_sql_query('SELECT * FROM source_provenance ORDER BY source_fid', db)
        pd.testing.assert_frame_equal(restored, lineage, check_dtype=False)
        unresolved = db.execute('''WITH variants AS (
            SELECT StructureID, 'structures' AS layer FROM structures UNION ALL
            SELECT StructureID, 'conflict_review' FROM conflict_review UNION ALL
            SELECT StructureID, 'geometry_quarantine' FROM geometry_quarantine)
            SELECT count(*) FROM source_provenance p LEFT JOIN variants v
            ON p.StructureID=v.StructureID AND p.OutputLayer=v.layer WHERE v.StructureID IS NULL''').fetchone()[0]
        if unresolved:
            raise ValueError("Unresolved provenance targets.")


def build_citywide(source: Path, output: Path) -> dict:
    """Publish verified internal artifacts to a new directory, never overwrite."""
    if output.exists():
        raise FileExistsError(output)
    inventory = source_inventory(source)
    fingerprint = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
    LOG.info("Reading source and auditing exact repeats")
    frame = pyogrio.read_dataframe(source, fid_as_index=True)
    layers, lineage, repair_log, report = prepare_citywide(frame, fingerprint)
    del frame
    if source_inventory(source) != inventory:
        raise ValueError("Source changed during processing.")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".citywide-", dir=output.parent))
    try:
        gpkg = stage / "toronto_citywide_internal.gpkg"
        for name, layer in layers.items():
            LOG.info("Writing %s: %s records", name, len(layer))
            layer.to_file(gpkg, layer=name, driver="GPKG", index=False, geometry_type="Unknown" if len(layer) else "MultiPolygon", promote_to_multi=False)
        with sqlite3.connect(gpkg) as db:
            lineage.to_sql("source_provenance", db, index=False, if_exists="fail")
            db.execute("CREATE UNIQUE INDEX lineage_source_fid ON source_provenance(source_fid)")
            db.execute("CREATE INDEX lineage_structure_id ON source_provenance(StructureID)")
            db.execute("INSERT INTO gpkg_contents(table_name, data_type, identifier, description) VALUES (?, 'attributes', ?, ?)",
                       ("source_provenance", "source_provenance", "Every original FID maps to a retained variant or quarantine record"))
        LOG.info("Verifying all exported geometry, attributes and provenance")
        verify_gpkg(gpkg, layers, lineage)
        repair_log.to_csv(stage / "geometry_changes.csv", index=False)
        report["source_bundle_sha256"] = fingerprint
        report["schema_version"] = SCHEMA
        report["automated_verification"] = "passed"
        (stage / "quality_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        manifest = {"schema_version": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "internal_only_not_for_customer_delivery", "original_source": str(source.resolve()),
            "source_members_sha256": inventory, "source_bundle_sha256": fingerprint,
            "source_as_of": None, "source_release_label": "2025 filename; observation vintage unverified",
            "source_url": "https://open.toronto.ca/dataset/3d-massing/",
            "attribution": "Contains information licensed under the Open Government Licence – Toronto.",
            "identity_method": "unchanged source bundle + lowest OGR FID among exact repeats; not persistent building identity",
            "crs": {"source": "EPSG:3857", "area": "EPSG:26917", "delivery": "EPSG:4326"},
            "height_policy": "MIN_HEIGHT zero becomes null, raw preserved; other fields unchanged; units/semantics unverified",
            "pending": ["commercial_use_review", "suitability_review", "building_identity_review", "QGIS inspection"],
            "files": {p.name: checksum(p) for p in stage.iterdir() if p.is_file()}}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        stage.rename(output)
    except Exception:
        shutil.rmtree(stage)
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(build_citywide(args.source_file, args.output_dir), indent=2))
