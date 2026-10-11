"""Audit exact normalized 2D duplicate footprints without changing source records."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely import force_2d, normalize, to_wkb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_toronto_internal_sample import source_inventory


def audit_groups(frame: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, pd.DataFrame, dict]:
    """Compare raw attributes and full dimensional geometry within equal XY groups.

    No snapping, rounding, repair, source-label normalization, or zero-to-null
    transformation occurs. Exact repeats are observationally indistinguishable
    records, not a proof of real-world building identity. Runtime is linear in
    geometry size plus grouped comparisons over duplicate records.
    """
    if frame.crs is None or not frame.index.is_unique:
        raise ValueError("Require declared CRS and unique source FIDs.")
    attributes = [c for c in frame.columns if c != frame.geometry.name]
    keys = pd.Series(to_wkb(normalize(force_2d(frame.geometry.array))), index=frame.index)
    eligible = frame.geometry.notna() & ~frame.geometry.is_empty
    mask = eligible & keys.duplicated(keep=False)
    members = frame.loc[mask].copy()
    members["source_fid"] = members.index
    members["duplicate_group"] = keys.loc[mask].map(lambda value: hashlib.sha256(value).hexdigest())
    members["geometry_3d_key"] = [hashlib.sha256(value).hexdigest() for value in to_wkb(normalize(members.geometry.array))]
    members["audit_class"] = ""
    members["repeat_of_fid"] = pd.Series(pd.NA, index=members.index, dtype="Int64")
    rows = []
    for key, group in members.groupby("duplicate_group", sort=True):
        group = group.sort_index()
        differing = [c for c in attributes if group[c].nunique(dropna=False) > 1]
        comparison = attributes + ["geometry_3d_key"]
        unique_count = len(group.drop_duplicates(comparison))
        z_variants = int(group.geometry_3d_key.nunique())
        category = ("exact_record_repeats" if unique_count == 1 else
                    "different_3d_geometry_unresolved" if z_variants > 1 else "attribute_conflict_unresolved")
        members.loc[group.index, "audit_class"] = category
        # Lowest FID is only an audit representative, never an authority ranking.
        for _, cluster in group.groupby(comparison, dropna=False, sort=False):
            ids = sorted(cluster.index)
            if len(ids) > 1:
                members.loc[ids[1:], "repeat_of_fid"] = int(ids[0])
        row = {"duplicate_group": key, "records": len(group), "distinct_record_variants": unique_count,
               "exact_repeat_excess": len(group) - unique_count, "audit_class": category,
               "geometry_3d_variants": z_variants, "differing_fields": ";".join(differing),
               "source_fids": ";".join(str(i) for i in sorted(group.index)),
               "invalid_geometry_records": int((~group.geometry.is_valid).sum())}
        for c in ("MIN_HEIGHT", "MAX_HEIGHT", "AVG_HEIGHT", "HEIGHT_MSL", "SURF_ELEV"):
            if c in group:
                row[c + "_values"] = json.dumps(group[c].drop_duplicates().tolist())
        for c in ("HEIGHT_SRC", "BLDG_SRC"):
            if c in group:
                row[c + "_values"] = json.dumps(group[c].drop_duplicates().tolist())
        rows.append(row)
    groups = pd.DataFrame(rows, columns=list(rows[0]) if rows else [
        "duplicate_group", "records", "distinct_record_variants", "exact_repeat_excess", "audit_class"])
    counts = groups.groupby("audit_class").agg(groups=("records", "size"), records=("records", "sum"),
                exact_repeat_excess=("exact_repeat_excess", "sum")).to_dict("index") if len(groups) else {}
    summary = {"input_records": len(frame), "duplicate_geometry_records": len(members), "duplicate_groups": len(groups),
               "nonduplicate_or_ineligible_records": len(frame)-len(members), "classes": counts,
               "exact_repeat_excess_all_groups": int(groups.exact_repeat_excess.sum()),
               "group_sizes": groups.records.value_counts().sort_index().to_dict(),
               "confirmed_building_component_groups": 0,
               "component_confirmation": "Unavailable: no component IDs, hierarchy, or verified vertical semantics.",
               "scope": "Exact normalized XY coordinate duplicates only; no near-duplicate, overlap, or adjacency search.",
               "actions_applied": "none; all original records retained",
               "accounting_reconciled": int(groups.records.sum()) == len(members)}
    return members.sort_values(["duplicate_group", "source_fid"]), groups, summary


def run_audit(source: Path, output: Path) -> dict:
    """Write source-fingerprinted CSV and QGIS review layers atomically."""
    if output.exists():
        raise FileExistsError(output)
    inventory = source_inventory(source)
    frame = pyogrio.read_dataframe(source, fid_as_index=True)
    members, groups, summary = audit_groups(frame)
    if inventory != source_inventory(source):
        raise ValueError("Source changed during audit.")
    summary["original_members_sha256"] = inventory
    summary["source_crs"] = str(frame.crs)
    summary["source_path"] = str(source.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".duplicate-audit-", dir=output.parent))
    try:
        groups.to_csv(stage / "groups.csv", index=False)
        conflicts = members[members.audit_class != "exact_record_repeats"]
        members.drop(columns=members.geometry.name).to_csv(stage / "members.csv", index=False)
        conflicts.drop(columns=members.geometry.name).to_csv(stage / "conflicts.csv", index=False)
        if not members.empty:
            members.to_file(stage / "duplicate_review.gpkg", layer="all_duplicate_records", index=False)
            if not conflicts.empty:
                conflicts.to_file(stage / "duplicate_review.gpkg", layer="unresolved_records", index=False)
        (stage / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        stage.rename(output)
    except Exception:
        shutil.rmtree(stage)
        raise
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_audit(args.source_file, args.output_dir), indent=2))
