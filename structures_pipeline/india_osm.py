from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import shapely
from shapely.validation import make_valid

from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS, SQM_TO_SQFT
from structures_pipeline.exposure import (
    ExposureValidationError,
    assign_structures_to_wards,
    normalize_ward_frame,
)
from structures_pipeline.utils import json_safe
from structures_pipeline.validation import validate_output

CHENNAI_CITY = "Chennai"
CHENNAI_STATE = "Tamil Nadu"
CHENNAI_STATE_CODE = "TN"
CHENNAI_PLACE_ID = "IN-TN-CHENNAI"
CHENNAI_PROJECTED_CRS = "EPSG:32644"
OSM_SOURCE_NAME = "openstreetmap"
OSM_SOURCE_AUTHORITY = "OpenStreetMap contributors"
OSM_SOURCE_FAMILY = "open_community"
OSM_PROVENANCE_TIER = "open_community"
CHENNAI_CANONICAL_COLUMNS = [
    *REQUIRED_OUTPUT_COLUMNS,
    "SourceAuthority",
    "SourceFamily",
    "ProvenanceTier",
]

OSM_TYPE_MAP = {
    "apartments": "residential",
    "bungalow": "residential",
    "detached": "residential",
    "dormitory": "residential",
    "house": "residential",
    "residential": "residential",
    "semidetached_house": "residential",
    "terrace": "residential",
    "commercial": "commercial",
    "office": "commercial",
    "retail": "commercial",
    "supermarket": "commercial",
    "industrial": "industrial",
    "warehouse": "warehouse",
    "civic": "public",
    "college": "public",
    "fire_station": "public",
    "government": "public",
    "hospital": "public",
    "kindergarten": "public",
    "police": "public",
    "public": "public",
    "school": "public",
    "university": "public",
    "church": "religious",
    "mosque": "religious",
    "religious": "religious",
    "shrine": "religious",
    "temple": "religious",
}


class ChennaiSourceValidationError(ValueError):
    """Raised when Chennai source data cannot satisfy the canonical contract."""


def load_source_manifest(path: Path) -> dict:
    """Load the acquisition receipt and require ready GCC ward and OSM building sources."""
    if not path.is_file():
        raise ChennaiSourceValidationError(f"Source manifest does not exist: {path}")
    manifest = json.loads(path.read_text())
    if manifest.get("gcc_wards", {}).get("status") != "ready":
        raise ChennaiSourceValidationError("GCC wards are not marked ready in the source manifest")
    if manifest.get("osm", {}).get("status") != "ready":
        raise ChennaiSourceValidationError("OSM is not marked ready in the source manifest")
    expected_wards = manifest.get("gcc_wards", {}).get("features")
    expected_buildings = manifest.get("osm", {}).get("feature_counts", {}).get("buildings")
    if not isinstance(expected_wards, int) or not isinstance(expected_buildings, int):
        raise ChennaiSourceValidationError("Source manifest is missing ward/building feature counts")
    return manifest


def load_osm_buildings(path: Path, *, expected_count: int | None = None) -> gpd.GeoDataFrame:
    """Read only required OSM fields and block IDs or geometries that cannot be audited."""
    if not path.is_file():
        raise ChennaiSourceValidationError(f"OSM buildings file does not exist: {path}")
    buildings = gpd.read_file(path, columns=["osm_id", "building", "name", "geometry"])
    missing = {"osm_id", "building", "geometry"} - set(buildings.columns)
    if missing:
        raise ChennaiSourceValidationError(f"OSM buildings are missing fields: {sorted(missing)}")
    if expected_count is not None and len(buildings) != expected_count:
        raise ChennaiSourceValidationError(
            f"OSM manifest count is {expected_count}, but the file contains {len(buildings)} features"
        )
    if buildings.crs is None:
        raise ChennaiSourceValidationError("OSM buildings CRS is missing")
    if buildings.crs.to_epsg() != 4326:
        buildings = buildings.to_crs("EPSG:4326")
    if buildings["osm_id"].isna().any():
        raise ChennaiSourceValidationError("OSM buildings contain null osm_id values")
    duplicate_source_ids = int(buildings["osm_id"].astype(str).duplicated().sum())
    if duplicate_source_ids:
        raise ChennaiSourceValidationError(f"OSM buildings contain duplicate osm_id values: {duplicate_source_ids}")

    invalid = buildings.geometry.notna() & ~buildings.geometry.is_empty & ~buildings.geometry.is_valid.fillna(False)
    repaired_count = int(invalid.sum())
    if repaired_count:
        buildings.loc[invalid, "geometry"] = buildings.loc[invalid, "geometry"].map(make_valid)
    unusable = (
        buildings.geometry.isna()
        | buildings.geometry.is_empty
        | ~buildings.geometry.is_valid.fillna(False)
        | ~buildings.geom_type.isin(["Polygon", "MultiPolygon"])
    )
    if unusable.any():
        raise ChennaiSourceValidationError(f"OSM buildings contain unusable geometries: {int(unusable.sum())}")
    buildings.attrs["repaired_geometry_count"] = repaired_count
    return buildings


def quarantine_exact_footprint_duplicates(
    buildings: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, list[dict[str, Any]]]:
    """Keep the lowest OSM ID for exact duplicate geometry and return an audit quarantine."""
    ordered = buildings.assign(_osm_sort=pd.to_numeric(buildings["osm_id"], errors="coerce")).sort_values(
        ["_osm_sort", "osm_id"],
        kind="stable",
        na_position="last",
    )
    geometry_key = pd.Series(
        shapely.to_wkb(shapely.normalize(ordered.geometry.array), hex=True),
        index=ordered.index,
    )
    duplicate = geometry_key.duplicated(keep="first")
    quarantine = [
        {
            "osm_id": str(row.osm_id),
            "reason": "exact_duplicate_footprint",
        }
        for row in ordered.loc[duplicate, ["osm_id"]].itertuples(index=False)
    ]
    retained = ordered.loc[~duplicate].drop(columns="_osm_sort").sort_index().copy()
    return retained, quarantine


def build_chennai_osm_structures(
    *,
    buildings_path: Path,
    wards_path: Path,
    manifest_path: Path,
    data_refresh_timestamp: str | None = None,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict]:
    """Build Chennai canonical structures from real OSM footprints inside GCC wards."""
    manifest = load_source_manifest(manifest_path)
    source_as_of = str(manifest.get("updated") or "")
    refresh_timestamp = data_refresh_timestamp or datetime.now(UTC).replace(microsecond=0).isoformat()
    wards = normalize_ward_frame(
        gpd.read_file(wards_path),
        ward_id_column="ward_id",
        expected_ward_count=int(manifest["gcc_wards"]["features"]),
        allow_overlaps=True,
    )
    buildings = load_osm_buildings(
        buildings_path,
        expected_count=int(manifest["osm"]["feature_counts"]["buildings"]),
    )
    raw_count = len(buildings)
    repaired_count = int(buildings.attrs.get("repaired_geometry_count", 0))
    buildings, duplicate_quarantine = quarantine_exact_footprint_duplicates(buildings)
    buildings["StructureID"] = "osm_building_" + buildings["osm_id"].astype(str)
    assigned, assignment = assign_structures_to_wards(
        buildings,
        wards,
        ward_id_column="ward_id",
        resolve_ambiguous_by_largest_overlap=True,
    )
    if assignment["ambiguous_count"]:
        raise ExposureValidationError(
            f"Unresolved ward assignments remain: {assignment['ambiguous_count']}"
        )

    canonical = _canonical_osm_frame(assigned, refresh_timestamp, source_as_of)
    qa = validate_output(canonical)
    reconciliation = {
        "raw_candidate_count": raw_count,
        "exact_duplicate_quarantine_count": len(duplicate_quarantine),
        "outside_gcc_aoi_count": assignment["unassigned_count"],
        "canonical_count": len(canonical),
        "reconciled": (
            raw_count
            == len(duplicate_quarantine) + assignment["unassigned_count"] + len(canonical)
        ),
    }
    if not reconciliation["reconciled"]:
        raise ChennaiSourceValidationError(f"Source counts do not reconcile: {reconciliation}")
    report = {
        "status": "passed",
        "city": CHENNAI_CITY,
        "state": CHENNAI_STATE,
        "source_as_of": source_as_of,
        "data_refresh_timestamp": refresh_timestamp,
        "source_manifest": str(manifest_path),
        "source_counts": reconciliation,
        "geometry_repaired_count": repaired_count,
        "duplicate_quarantine": duplicate_quarantine,
        "ward_assignment": assignment,
        "ward_overlap_diagnostics": wards.attrs.get("overlap_diagnostics", {}),
        "quality": qa,
        "attribute_completeness": {
            "structure_type": float(canonical["StructureType"].notna().mean()),
            "num_stories": float(canonical["NumStories"].notna().mean()),
            "num_units": float(canonical["NumUnits"].notna().mean()),
            "occupant_count": float(canonical["OccupantCount"].notna().mean()),
        },
        "known_gaps": [
            "OSM building tags are incomplete and are not treated as authoritative municipal attributes.",
            "Stories, units, and occupant count remain null because no trusted Chennai source is configured.",
            "Footprints outside the supplied GCC ward AOI are excluded and counted.",
        ],
    }
    return canonical, wards, json_safe(report)


def _canonical_osm_frame(
    buildings: gpd.GeoDataFrame,
    refresh_timestamp: str,
    source_as_of: str,
) -> gpd.GeoDataFrame:
    """Map audited OSM rows into the canonical schema without estimating attributes."""
    frame = gpd.GeoDataFrame(index=buildings.index, geometry=buildings.geometry, crs="EPSG:4326")
    for column in CHENNAI_CANONICAL_COLUMNS:
        if column != "geometry":
            frame[column] = pd.NA
    raw_type = buildings["building"].astype("string").str.strip().str.lower()
    mapped_type = raw_type.map(OSM_TYPE_MAP)
    projected_area = buildings.to_crs(CHENNAI_PROJECTED_CRS).geometry.area
    frame["StructureID"] = buildings["StructureID"].astype(str)
    frame["PlaceGEOID"] = CHENNAI_PLACE_ID
    frame["City"] = CHENNAI_CITY
    frame["State"] = CHENNAI_STATE
    frame["StateFP"] = CHENNAI_STATE_CODE
    frame["Country"] = "India"
    frame["created_at"] = refresh_timestamp
    frame["updated_at"] = refresh_timestamp
    frame["updated_by"] = "chennai_real_source_refresh"
    frame["change_log"] = "[]"
    frame["data_refresh_timestamp"] = refresh_timestamp
    frame["last_refreshed"] = refresh_timestamp
    frame["source_as_of"] = source_as_of
    frame["CoverageTier"] = "Tier 4"
    frame["LoadSource"] = OSM_SOURCE_NAME
    frame["RawDataSource"] = OSM_SOURCE_NAME
    frame["FootprintSource"] = OSM_SOURCE_NAME
    frame["StructureTypeRaw"] = raw_type.where(raw_type.ne(""))
    frame["StructureType"] = mapped_type
    frame["StructureTypeSource"] = OSM_SOURCE_NAME
    frame.loc[mapped_type.isna(), "StructureTypeSource"] = pd.NA
    frame["FootprintArea_m2"] = projected_area.to_numpy()
    frame["FootprintArea_sqft"] = frame["FootprintArea_m2"] * SQM_TO_SQFT
    frame["SourceAuthority"] = OSM_SOURCE_AUTHORITY
    frame["SourceFamily"] = OSM_SOURCE_FAMILY
    frame["ProvenanceTier"] = OSM_PROVENANCE_TIER
    frame["geometry_wkt"] = frame.geometry.to_wkt(rounding_precision=-1)
    return frame[CHENNAI_CANONICAL_COLUMNS].reset_index(drop=True)
