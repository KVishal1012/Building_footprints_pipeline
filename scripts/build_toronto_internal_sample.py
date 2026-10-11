"""Adapt a local Toronto massing shapefile into a bounded internal-only sample."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from structures_pipeline.toronto import build_toronto_pack, checksum

FIELDS = {"MIN_HEIGHT", "MAX_HEIGHT", "AVG_HEIGHT", "HEIGHT_MSL", "SURF_ELEV",
          "HEIGHT_SRC", "BLDG_SRC", "LONGITUDE", "LATITUDE"}


def source_inventory(path: Path) -> dict:
    """Fingerprint required shapefile members and available ancillary metadata."""
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        if not path.with_suffix(suffix).is_file():
            raise ValueError(f"Missing required shapefile member: {suffix}")
    return {p.name: checksum(p) for p in sorted(path.parent.glob(path.stem + ".*")) if p.is_file()}


def build_sample(source: Path, output: Path, longitude: float = -79.62054585,
                 latitude: float = 43.72219469, size_m: float = 200) -> dict:
    """Create a complete square-area sample, refusing truncation above 500 records.

    Source FIDs plus the complete bundle fingerprint identify snapshot records,
    not enduring real-world buildings. No source review is marked approved.
    """
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    if source.suffix.lower() != ".shp" or not 0 < size_m <= 1000:
        raise ValueError("Require a .shp input and a square side length in (0, 1000] metres.")
    if not (-79.65 <= longitude <= -79.10 and 43.57 <= latitude <= 43.90):
        raise ValueError("Sample centre is outside the Toronto sanity envelope.")
    inventory = source_inventory(source)
    fingerprint = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
    point = gpd.GeoSeries([Point(longitude, latitude)], crs=4326).to_crs(26917).iloc[0]
    half = size_m / 2
    boundary = gpd.GeoDataFrame({"purpose": ["internal demonstration; user-row vicinity"]},
        geometry=[box(point.x-half, point.y-half, point.x+half, point.y+half)], crs=26917)
    import pyogrio
    info = pyogrio.read_info(source)
    if info["crs"] != "EPSG:3857":
        raise ValueError(f"Expected inspected massing CRS EPSG:3857; found {info['crs']}")
    bbox = tuple(boundary.to_crs(3857).total_bounds)
    frame = pyogrio.read_dataframe(source, bbox=bbox, fid_as_index=True)
    if not FIELDS.issubset(frame.columns):
        raise ValueError(f"Missing massing fields: {sorted(FIELDS - set(frame.columns))}")
    if frame.empty or len(frame) > 500:
        raise ValueError(f"Bounding-box selection has {len(frame)} records; choose a smaller/nonempty area. No truncation applied.")
    frame["SnapshotRecordID"] = [f"{fingerprint}:{fid}" for fid in frame.index]
    frame = frame.reset_index(drop=True)
    if source_inventory(source) != inventory:
        raise ValueError("Shapefile changed during acquisition.")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".massing-", dir=output.parent))
    try:
        frame.to_file(stage / "source_subset.gpkg", layer="source_records", index=False)
        boundary.to_file(stage / "study_area.gpkg", layer="study_area", index=False)
        now = datetime.now(timezone.utc).isoformat()
        manifest = {"source_name": "toronto_3d_massing_2025", "source_url": "https://open.toronto.ca/dataset/3d-massing/",
            "license_url": "https://open.toronto.ca/open-data-licence/",
            "attribution": "Contains information licensed under the Open Government Licence – Toronto.",
            "retrieved_at": now, "retrieval_event": "local subset read; original download time unknown",
            "source_as_of": None, "source_release_label": "2025 (filename, not verified observation date)",
            "source_sha256": checksum(stage / "source_subset.gpkg"), "id_column": "SnapshotRecordID",
            "reviewed_by": "automated internal inspection", "reviewed_at": now,
            "review_notes": "Internal processing only; not rights, suitability, or building identity approval.",
            "commercial_use_review": "pending", "suitability_review": "context_only_unverified",
            "identity_review": "snapshot_records_only", "identity_method": "bundle_sha256_and_OGR_FID; unstable across source updates",
            "original_source": str(source.resolve()), "original_members_sha256": inventory,
            "original_feature_count": int(info["features"]), "source_crs": info["crs"],
            "selection": {"method": "source_crs_bbox_then_exact_intersection_in_pipeline", "bbox": bbox,
                          "bbox_rows": len(frame), "square_side_m": size_m, "centre_lonlat": [longitude, latitude]},
            "limitations": ["Internal sample only; not approved for customer delivery.",
                "Massing records are not verified distinct buildings; duplicate geometries are quarantined.",
                "Height units and semantics remain unverified; only MIN_HEIGHT zero is provisionally mapped to null.",
                "Original observation vintage and original download time are unknown.",
                "Source is illustrative/context data, not a surveyed or legally verified inventory.",
                "No desktop GIS inspection has been completed."]}
        manifest_path = stage / "source_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        release = build_toronto_pack(stage / "source_subset.gpkg", manifest_path, stage / "study_area.gpkg",
                                     stage / "package", internal_only=True)
        stage.rename(output)
        return release
    except Exception:
        shutil.rmtree(stage)
        raise


def main() -> None:
    """Read CLI paths and emit the internal release summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--longitude", type=float, default=-79.62054585)
    parser.add_argument("--latitude", type=float, default=43.72219469)
    parser.add_argument("--size-m", type=float, default=200)
    args = parser.parse_args()
    print(json.dumps(build_sample(args.source_file, args.output_dir, args.longitude, args.latitude, args.size_m), indent=2))


if __name__ == "__main__":
    main()
