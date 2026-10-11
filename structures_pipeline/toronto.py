"""Bounded, file-only Toronto pilot delivery; no database promotion or inference."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import force_2d, make_valid, normalize
from shapely.geometry import box

LOG = logging.getLogger(__name__)
ANALYSIS_CRS = 26917
MAX_AREA_M2 = 5_000_000
MAX_FEATURES = 5_000
OPTIONAL_ATTRIBUTES = ("StructureType", "NumStories", "NumUnits", "OccupantCount")


def checksum(path: Path) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_vector(path: Path) -> gpd.GeoDataFrame:
    """Read one self-contained vector file, requiring an explicit CRS."""
    if path.suffix.lower() not in {".gpkg", ".geojson", ".parquet", ".geoparquet"}:
        raise ValueError("Use a single-layer GeoPackage, GeoJSON, or GeoParquet file.")
    if path.suffix.lower() == ".gpkg" and len(gpd.list_layers(path)) != 1:
        raise ValueError("Input GeoPackage must contain exactly one layer.")
    frame = gpd.read_parquet(path) if path.suffix.lower() in {".parquet", ".geoparquet"} else gpd.read_file(path)
    if frame.crs is None:
        raise ValueError(f"Missing CRS: {path.name}; supply correctly declared source data.")
    return frame


def validate_manifest(manifest: dict, source_file: Path, *, internal_only: bool = False) -> None:
    """Require explicit source, rights, suitability, and identity review."""
    if not isinstance(manifest, dict):
        raise ValueError("Source manifest must be a JSON object.")
    required = ("source_name", "source_url", "license_url", "attribution", "retrieved_at",
                "source_sha256", "id_column", "reviewed_by", "reviewed_at", "review_notes")
    for key in required:
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError(f"Source manifest requires nonempty {key}.")
    for key in ("commercial_use_review", "suitability_review"):
        if not internal_only and manifest.get(key) != "approved":
            raise ValueError(f"Source manifest {key} must be approved before delivery.")
    if not internal_only and manifest.get("identity_review") != "one_record_per_building":
        raise ValueError("Source identity must be reviewed as one_record_per_building.")
    if "source_as_of" not in manifest or (manifest["source_as_of"] is not None and
            (not isinstance(manifest["source_as_of"], str) or not manifest["source_as_of"].strip())):
        raise ValueError("source_as_of must be a documented vintage or explicit null.")
    if not isinstance(manifest.get("limitations"), list) or not manifest["limitations"] or not all(
        isinstance(item, str) and item.strip() for item in manifest["limitations"]
    ):
        raise ValueError("Document at least one source limitation.")
    for key in ("retrieved_at", "reviewed_at"):
        stamp = datetime.fromisoformat(manifest[key].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError(f"{key} requires a timezone.")
    if checksum(source_file) != manifest["source_sha256"]:
        raise ValueError("Source checksum differs from reviewed manifest.")


def prepare_buildings(source: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame,
                      manifest: dict) -> tuple[gpd.GeoDataFrame, pd.DataFrame, dict]:
    """Clean and select complete intersecting footprints with full row accounting.

    Repairs are restricted to polygon inputs yielding valid polygon outputs.
    Duplicate identifiers and duplicate geometry are quarantined as groups;
    no arbitrary winner is selected. IDs derive from source namespace and ID.
    """
    if source.crs is None or boundary.crs is None:
        raise ValueError("Both source and study area require a known CRS.")
    if boundary.empty or not boundary.geometry.notna().all() or not (
        boundary.geometry.is_valid & ~boundary.geometry.is_empty &
        boundary.geom_type.isin(["Polygon", "MultiPolygon"])
    ).all():
        raise ValueError("Study area must contain valid nonempty polygon geometry.")
    # Sanity envelope only; never represented as an authoritative city boundary.
    if not box(-79.65, 43.57, -79.10, 43.90).covers(boundary.to_crs(4326).geometry.union_all()):
        raise ValueError("Study area is outside the Toronto sanity envelope.")
    area = boundary.to_crs(ANALYSIS_CRS).geometry.union_all()
    if not 0 < area.area <= MAX_AREA_M2:
        raise ValueError("Study area exceeds the 5 km² pilot limit or has zero area.")
    id_column = manifest["id_column"]
    if id_column not in source:
        raise ValueError(f"Source is missing identifier column {id_column}.")
    ids = source[id_column].astype("string").str.strip()
    duplicate_ids = ids.duplicated(keep=False)
    projected = source.to_crs(ANALYSIS_CRS)
    candidates, rejected = [], []
    outside = 0
    for position, (identifier, geom) in enumerate(zip(ids, projected.geometry)):
        reason = None
        repaired = False
        flattened = bool(geom is not None and geom.has_z)
        if pd.isna(identifier) or not identifier:
            reason = "missing_source_id"
        elif duplicate_ids.iloc[position]:
            reason = "duplicate_source_id"
        elif geom is None or geom.is_empty:
            reason = "empty_geometry"
        elif geom.geom_type not in {"Polygon", "MultiPolygon"}:
            reason = "non_polygon_geometry"
        else:
            geom = force_2d(geom)
            if not geom.is_valid:
                geom, repaired = make_valid(geom), True
            if (geom.geom_type not in {"Polygon", "MultiPolygon"} or geom.is_empty or
                    not geom.is_valid or not math.isfinite(geom.area) or not geom.area > 0):
                reason = "repair_not_valid_polygon"
        if reason:
            rejected.append({"source_row": position, "SourceRecordID": None if pd.isna(identifier) else str(identifier), "reason": reason})
        elif not geom.intersects(area):
            outside += 1
        else:
            candidates.append({"source_row": position, "SourceRecordID": str(identifier), "geometry": normalize(geom),
                               "GeometryRepaired": repaired, "ZRemoved": flattened,
                               "BoundaryCrossing": not area.covers(geom)})
    selected_count = len(candidates)
    if selected_count > MAX_FEATURES:
        raise ValueError("Study area exceeds the 5,000 source-feature pilot limit.")
    hashes = pd.Series([row["geometry"].wkb_hex for row in candidates], dtype="string")
    duplicates = hashes.duplicated(keep=False)
    kept = []
    for i, row in enumerate(candidates):
        if duplicates.iloc[i]:
            rejected.append({"source_row": row["source_row"], "SourceRecordID": row["SourceRecordID"], "reason": "duplicate_geometry"})
        else:
            kept.append(row)
    if not kept:
        raise ValueError("No releasable buildings in study area; no package published.")
    frame = gpd.GeoDataFrame(kept, crs=ANALYSIS_CRS)
    # User-approved interim rule, not a confirmed upstream field definition.
    raw_min = (pd.to_numeric(source["MIN_HEIGHT"], errors="raise").iloc[frame.source_row].reset_index(drop=True)
               if "MIN_HEIGHT" in source else pd.Series(float("nan"), index=frame.index))
    if not raw_min.dropna().map(math.isfinite).all():
        raise ValueError("MIN_HEIGHT contains non-finite values.")
    for column in ("MAX_HEIGHT", "AVG_HEIGHT", "HEIGHT_MSL", "SURF_ELEV", "HEIGHT_SRC", "BLDG_SRC", "LONGITUDE", "LATITUDE"):
        if column in source:
            frame[column] = source[column].iloc[frame.source_row].reset_index(drop=True)
    frame["MIN_HEIGHT_RAW"] = raw_min
    frame["MIN_HEIGHT"] = raw_min.mask(raw_min.eq(0))
    frame["MinHeightStatus"] = "source_value_unverified"
    frame.loc[raw_min.isna(), "MinHeightStatus"] = "source_missing"
    frame.loc[raw_min.eq(0), "MinHeightStatus"] = "zero_assumed_missing"
    frame["MinHeightMethod"] = "zero_to_null_provisional_project_rule"
    frame["FootprintArea_m2"] = frame.area
    frame["FootprintAreaSource"] = manifest["source_name"]
    frame["FootprintAreaMethod"] = "area_of_prepared_full_footprint_epsg_26917"
    frame["StructureID"] = frame.SourceRecordID.map(lambda value: "toronto_" + hashlib.sha256(
        json.dumps([manifest["source_name"], value], ensure_ascii=False).encode("utf-8")).hexdigest())
    for column in ("LoadSource", "RawDataSource", "FootprintSource"):
        frame[column] = manifest["source_name"]
    for column, value in {"City": "Toronto", "State": "Ontario", "Country": "Canada",
                          "CoverageTier": "unassessed", "source_as_of": manifest["source_as_of"]}.items():
        frame[column] = value
    for column in (*OPTIONAL_ATTRIBUTES, "PlaceGEOID", "StateFP"):
        frame[column] = None
    frame = frame.drop(columns="source_row").sort_values("StructureID").reset_index(drop=True).to_crs(4326)
    issues = pd.DataFrame(rejected, columns=["source_row", "SourceRecordID", "reason"])
    report = {"input_rows": len(source), "outside_study_area": outside, "output_rows": len(frame),
              "rejected_rows": len(issues), "selected_before_geometry_deduplication": selected_count,
              "repaired_output_rows": int(frame.GeometryRepaired.sum()),
              "flattened_output_rows": int(frame.ZRemoved.sum()),
              "boundary_crossing_rows": int(frame.BoundaryCrossing.sum()),
              "study_area_m2": area.area, "analysis_crs": "EPSG:26917", "delivery_crs": "EPSG:4326",
              "missing_attributes": {column: len(frame) for column in OPTIONAL_ATTRIBUTES},
              "min_height_zero_assumed_missing": int(frame.MinHeightStatus.eq("zero_assumed_missing").sum()),
              "completeness_against_real_world": "not_verified",
              "accounting_reconciled": len(source) == len(frame) + outside + len(issues)}
    if not report["accounting_reconciled"] or not frame.geometry.is_valid.all():
        raise ValueError("Output geometry/accounting validation failed.")
    return frame, issues, report


def build_toronto_pack(source_file: Path, source_manifest: Path, study_area: Path,
                       output_dir: Path, *, internal_only: bool = False) -> dict:
    """Validate inputs and atomically publish a new local delivery directory.

    Existing directories are never overwritten. Failed runs leave no release.
    Generated timestamps may differ; unchanged inputs preserve IDs/attributes.
    """
    if output_dir.exists():
        raise FileExistsError(f"Output already exists: {output_dir}; choose a new release directory.")
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    validate_manifest(manifest, source_file, internal_only=internal_only)
    boundary_hash = checksum(study_area)
    frame, rejected, report = prepare_buildings(read_vector(source_file), read_vector(study_area), manifest)
    if checksum(source_file) != manifest["source_sha256"] or checksum(study_area) != boundary_hash:
        raise ValueError("Inputs changed during processing.")
    now = datetime.now(timezone.utc).isoformat()
    frame["data_refresh_timestamp"] = now
    report["desktop_gis_review"] = "pending"
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".toronto-", dir=output_dir.parent))
    try:
        frame.to_file(stage / "buildings.gpkg", layer="buildings", driver="GPKG", index=False)
        roundtrip = gpd.read_file(stage / "buildings.gpkg")
        if (len(roundtrip) != len(frame) or roundtrip.crs.to_epsg() != 4326 or
                roundtrip.StructureID.tolist() != frame.StructureID.tolist() or
                not roundtrip.geometry.is_valid.all() or
                not roundtrip.geometry.geom_equals_exact(frame.geometry, tolerance=1e-12).all() or
                not roundtrip.FootprintArea_m2.equals(frame.FootprintArea_m2)):
            raise ValueError("GeoPackage round-trip verification failed.")
        frame.drop(columns="geometry").to_csv(stage / "attributes.csv", index=False)
        rejected.to_csv(stage / "rejected_records.csv", index=False)
        for filename, value in (("source_manifest.json", manifest), ("quality_report.json", report)):
            (stage / filename).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (stage / "HANDOVER.md").write_text(
            "# Toronto study-area building data pack\n\n" +
            ("**INTERNAL SAMPLE ONLY: commercial use, building identity, and suitability are not qualified.**\n\n" if internal_only else
             "**Candidate delivery: desktop GIS inspection is still required before customer acceptance.**\n\n") +
            "Open buildings.gpkg in QGIS. Compare extent and a spatially distributed sample with the reviewed source. "
            "Check repaired and boundary-crossing features. Record reviewer, date, and findings before handover.\n\n"
            "Geometry: EPSG:4326. Area: full prepared footprint measured in EPSG:26917; footprints are not clipped. "
            "CSV joins on StructureID and contains no geometry. IDs are stable while source namespace and IDs remain stable.\n\n"
            "SourceRecordID is source-scoped; see manifest identity_method for any snapshot-only identity. GeometryRepaired, ZRemoved and BoundaryCrossing describe transformations. "
            "Source labels identify supplied geometry; FootprintAreaMethod describes the derived area. "
            "source_as_of is upstream vintage (null means unknown); data_refresh_timestamp is processing time. "
            "CoverageTier is unassessed. Unsupported building attributes and US identifiers are null.\n\n"
            "MIN_HEIGHT_RAW preserves supplied minimum height. MIN_HEIGHT converts zero to null under a provisional "
            "project assumption; MinHeightStatus distinguishes assumed missing, source missing, and unverified source values. "
            "MinHeightMethod records this rule. Units and upstream meaning remain unverified.\n\n"
            "Other source height fields and HEIGHT_SRC/BLDG_SRC are retained unchanged, including zeros. "
            "Their units and semantics are not independently verified. No height-based inference is made.\n\n"
            "Processing checks do not establish real-world completeness, survey accuracy, or fitness for official use. "
            "Rejected records are excluded, not silently repaired or filled. Source row numbers are zero-based.\n\n"
            "## Attribution\n\n" + manifest["attribution"] + "\n\n## Source limitations\n\n" +
            "\n".join("- " + item for item in manifest["limitations"]) + "\n", encoding="utf-8")
        fingerprint = hashlib.sha256(json.dumps(["toronto-pilot-1.2", internal_only, manifest, boundary_hash], sort_keys=True).encode()).hexdigest()
        release = {"release_id": "toronto-" + fingerprint[:20], "schema_version": "toronto-pilot-1.2",
                   "generated_at": now, "row_count": len(frame), "status": "internal_only_not_for_customer_delivery" if internal_only else "candidate_pending_desktop_review",
                   "quality_contract": {"release_gates": {"status": "pending", "blockers": (["commercial_use_review", "suitability_review", "building_identity_review", "desktop_gis_review"]
                                                                        if internal_only else ["desktop_gis_review"]),
                                                           "automated_checks": "passed"}, "ai_policy": "no_inference"},
                   "freshness": {"source_as_of": manifest["source_as_of"], "data_refresh_timestamp": now},
                   "coverage": {"tier": "unassessed", "real_world_completeness": "not_verified"},
                   "inputs": {"source_sha256": manifest["source_sha256"], "study_area_sha256": boundary_hash},
                   "delivery": {"formats": ["gpkg", "csv"], "files": {p.name: checksum(p) for p in sorted(stage.iterdir())}}}
        (stage / "release_manifest.json").write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
        stage.rename(output_dir)
    except Exception:
        shutil.rmtree(stage)
        raise
    LOG.info("Toronto pack: input=%s output=%s rejected=%s outside=%s", len(frame) + len(rejected) + report["outside_study_area"],
             len(frame), len(rejected), report["outside_study_area"])
    return release
