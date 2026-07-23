from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import wkt
from shapely.validation import make_valid

from structures_pipeline.utils import json_safe
from structures_pipeline.validation import CORE_ATTRIBUTE_SOURCES, validate_output

EXPOSURE_LAYER_VERSION = "structure-exposure-layer-v1"
TYPE_GROUPS = {
    "residential": {"residential", "apartments", "house", "detached"},
    "public": {"public", "school", "hospital", "university", "government", "civic"},
    "commercial": {"commercial", "retail", "office", "industrial", "warehouse"},
}


class ExposureValidationError(ValueError):
    """Raised when exposure inputs fail strict production gates."""


def load_structure_frame(path: Path) -> gpd.GeoDataFrame:
    """Load canonical structures and validate the release-gate contract."""
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        frame = gpd.read_parquet(path)
    elif suffix in {".geojson", ".json", ".gpkg", ".shp"}:
        frame = gpd.read_file(path)
    elif suffix == ".csv":
        table = pd.read_csv(path)
        if "geometry_wkt" not in table.columns:
            raise ExposureValidationError("Structure CSV input must include geometry_wkt")
        geometry = table["geometry_wkt"].map(lambda value: wkt.loads(str(value)) if _present(value) else None)
        frame = gpd.GeoDataFrame(table.drop(columns=["geometry_wkt"]), geometry=geometry, crs="EPSG:4326")
        frame["geometry_wkt"] = table["geometry_wkt"]
    else:
        raise ExposureValidationError(f"Unsupported structure input format: {path.suffix}")
    return normalize_structure_frame(frame)


def load_ward_frame(
    path: Path,
    *,
    ward_id_column: str = "ward_no",
    expected_ward_count: int | None = None,
    allow_overlaps: bool = False,
) -> gpd.GeoDataFrame:
    """Load wards and enforce identifier, geometry, count, and overlap gates."""
    return normalize_ward_frame(
        gpd.read_file(path),
        ward_id_column=ward_id_column,
        expected_ward_count=expected_ward_count,
        allow_overlaps=allow_overlaps,
    )


def normalize_structure_frame(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Normalize structures to EPSG:4326 and run canonical output gates."""
    if not isinstance(frame, gpd.GeoDataFrame):
        raise ExposureValidationError("Structures must be a GeoDataFrame")
    if frame.crs is None:
        frame = frame.set_crs("EPSG:4326")
    if frame.crs.to_epsg() != 4326:
        frame = frame.to_crs("EPSG:4326")
    out = frame.copy()
    if "geometry_wkt" not in out.columns:
        out["geometry_wkt"] = out.geometry.to_wkt(rounding_precision=-1)
    validate_output(out)
    return out


def normalize_ward_frame(
    wards: gpd.GeoDataFrame,
    *,
    ward_id_column: str = "ward_no",
    expected_ward_count: int | None = None,
    allow_overlaps: bool = False,
) -> gpd.GeoDataFrame:
    """Normalize wards and report polygon overlaps without hiding source defects."""
    if not isinstance(wards, gpd.GeoDataFrame):
        raise ExposureValidationError("Wards must be a GeoDataFrame")
    if ward_id_column not in wards.columns:
        raise ExposureValidationError(f"Ward input is missing required id column: {ward_id_column}")
    if wards.empty:
        raise ExposureValidationError("Ward input is empty")
    if wards.crs is None:
        wards = wards.set_crs("EPSG:4326")
    if wards.crs.to_epsg() != 4326:
        wards = wards.to_crs("EPSG:4326")
    out = wards.copy()
    out[ward_id_column] = out[ward_id_column].astype(str).str.strip()
    if out[ward_id_column].eq("").any():
        raise ExposureValidationError("Ward input has blank ward ids")
    duplicate_count = int(out[ward_id_column].duplicated().sum())
    if duplicate_count:
        raise ExposureValidationError(f"Ward input has duplicate ward ids: {duplicate_count}")
    invalid_mask = out.geometry.notna() & ~out.geometry.is_empty & ~out.geometry.is_valid.fillna(False)
    repaired_count = int(invalid_mask.sum())
    if repaired_count:
        out.loc[invalid_mask, "geometry"] = out.loc[invalid_mask, "geometry"].map(make_valid)
    invalid_count = int((out.geometry.isna() | out.geometry.is_empty | ~out.geometry.is_valid.fillna(False)).sum())
    if invalid_count:
        raise ExposureValidationError(f"Ward input has invalid/empty geometries: {invalid_count}")
    if expected_ward_count is not None and len(out) != expected_ward_count:
        raise ExposureValidationError(f"Expected {expected_ward_count} wards, found {len(out)}")
    normalized = out[[ward_id_column, "geometry"]].copy()
    overlap = _ward_overlap_diagnostics(normalized, ward_id_column)
    if overlap["overlap_pair_count"] and not allow_overlaps:
        raise ExposureValidationError(
            f"Ward polygons overlap in {overlap['overlap_pair_count']} pairs; "
            "set allow_overlaps=True only when the source defect is documented"
        )
    normalized.attrs["repaired_geometry_count"] = repaired_count
    normalized.attrs["overlap_diagnostics"] = overlap
    return normalized


def assign_structures_to_wards(
    structures: gpd.GeoDataFrame,
    wards: gpd.GeoDataFrame,
    *,
    ward_id_column: str = "ward_no",
    resolve_ambiguous_by_largest_overlap: bool = False,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Assign structures by representative point, resolving only unique overlap winners."""
    if ward_id_column not in wards:
        raise ExposureValidationError(f"Ward frame is missing id column: {ward_id_column}")
    source_indexes = list(structures.index)
    points = gpd.GeoDataFrame(
        {"_source_index": source_indexes, "StructureID": structures["StructureID"].astype(str).tolist()},
        geometry=structures.geometry.representative_point().tolist(),
        crs=structures.crs,
    )
    joined = gpd.sjoin(
        points,
        wards[[ward_id_column, "geometry"]],
        how="left",
        predicate="intersects",
    )
    joined[ward_id_column] = joined[ward_id_column].astype("string")
    match_counts = joined.groupby("_source_index", sort=False)[ward_id_column].count()
    direct_indices = match_counts[match_counts.eq(1)].index
    ambiguous_indices = match_counts[match_counts.gt(1)].index
    unassigned_indices = match_counts[match_counts.eq(0)].index
    assignments: dict[Any, tuple[str, str, float | None]] = {}
    direct = joined[joined["_source_index"].isin(direct_indices)].dropna(subset=[ward_id_column])
    for _, row in direct.iterrows():
        assignments[row["_source_index"]] = (
            str(row[ward_id_column]),
            "representative_point_intersects_ward",
            None,
        )

    resolved_ids: list[str] = []
    unresolved_ids: list[str] = []
    if len(ambiguous_indices):
        ambiguous_join = joined[joined["_source_index"].isin(ambiguous_indices)]
        if resolve_ambiguous_by_largest_overlap:
            projected_crs = wards.estimate_utm_crs() or "EPSG:3857"
            projected_structures = structures.loc[ambiguous_indices].to_crs(projected_crs)
            projected_wards = wards.to_crs(projected_crs)
            ward_lookup = projected_wards.set_index(ward_id_column).geometry
            for source_index, candidates in ambiguous_join.groupby("_source_index", sort=False):
                footprint = projected_structures.loc[source_index].geometry
                areas = [
                    (str(ward_id), float(footprint.intersection(ward_lookup.loc[str(ward_id)]).area))
                    for ward_id in candidates[ward_id_column].dropna().astype(str).unique()
                ]
                areas.sort(key=lambda item: item[1], reverse=True)
                structure_id = str(structures.loc[source_index, "StructureID"])
                if areas and (len(areas) == 1 or areas[0][1] > areas[1][1] + 1e-6):
                    ratio = areas[0][1] / float(footprint.area) if footprint.area else None
                    assignments[source_index] = (areas[0][0], "unique_largest_overlap", ratio)
                    resolved_ids.append(structure_id)
                else:
                    unresolved_ids.append(structure_id)
        else:
            unresolved_ids = structures.loc[ambiguous_indices, "StructureID"].astype(str).tolist()

    assigned_indices = list(assignments)
    assigned = structures.loc[assigned_indices].copy()
    if assigned_indices:
        assigned[ward_id_column] = [assignments[index][0] for index in assigned_indices]
        assigned["ward_assignment_method"] = [assignments[index][1] for index in assigned_indices]
        assigned["ward_assignment_overlap_ratio"] = [assignments[index][2] for index in assigned_indices]
        assigned["ward_assignment_status"] = "assigned"
    else:
        assigned[ward_id_column] = pd.Series(dtype="string")
        assigned["ward_assignment_method"] = pd.Series(dtype="string")
        assigned["ward_assignment_overlap_ratio"] = pd.Series(dtype="float64")
        assigned["ward_assignment_status"] = pd.Series(dtype="string")
    unassigned = structures.loc[unassigned_indices, "StructureID"].astype(str).tolist()
    return assigned, {
        "structure_count": int(len(structures)),
        "ward_count": int(len(wards)),
        "assigned_count": int(len(assigned)),
        "unassigned_count": int(len(unassigned)),
        "ambiguous_count": int(len(unresolved_ids)),
        "resolved_ambiguity_count": int(len(resolved_ids)),
        "unassigned_structure_ids": unassigned[:100],
        "ambiguous_structure_ids": unresolved_ids[:100],
        "resolved_ambiguity_structure_ids": resolved_ids[:100],
        "assignment_method": "representative_point_then_unique_largest_overlap",
    }


def build_ward_structure_exposure(
    structures: gpd.GeoDataFrame,
    wards: gpd.GeoDataFrame,
    *,
    strict: bool = True,
    expected_ward_count: int | None = None,
    ward_id_column: str = "ward_no",
    allow_ward_overlaps: bool = False,
    resolve_ambiguous_by_largest_overlap: bool = False,
) -> dict:
    """Build dashboard-ready ward-level structure exposure features without imputing values."""
    normalized_structures = normalize_structure_frame(structures)
    normalized_wards = normalize_ward_frame(
        wards,
        ward_id_column=ward_id_column,
        expected_ward_count=expected_ward_count,
        allow_overlaps=allow_ward_overlaps,
    )
    assigned, assignment = assign_structures_to_wards(
        normalized_structures,
        normalized_wards,
        ward_id_column=ward_id_column,
        resolve_ambiguous_by_largest_overlap=resolve_ambiguous_by_largest_overlap,
    )
    assignment["ward_geometry_repaired_count"] = int(normalized_wards.attrs.get("repaired_geometry_count", 0))
    assignment["ward_overlap_diagnostics"] = normalized_wards.attrs.get("overlap_diagnostics", {})
    blockers = []
    if assignment["ambiguous_count"]:
        blockers.append("ambiguous_structure_ward_assignment")
    if assignment["unassigned_count"]:
        blockers.append("unassigned_structure_ward_assignment")
    if strict and blockers:
        raise ExposureValidationError(f"Structure exposure assignment failed strict gates: {blockers}")
    assigned_by_ward = dict(tuple(assigned.groupby(ward_id_column, dropna=False))) if not assigned.empty else {}
    ward_features = []
    sorted_wards = sorted(
        normalized_wards.to_dict("records"),
        key=lambda row: _ward_sort_key(str(row[ward_id_column])),
    )
    for ward in sorted_wards:
        empty = assigned.iloc[0:0] if not assigned.empty else assigned
        ward_features.append(
            _ward_feature(
                str(ward[ward_id_column]),
                assigned_by_ward.get(str(ward[ward_id_column]), empty),
            )
        )
    metadata = {
        "feature_type": "structure_exposure",
        "feature_version": EXPOSURE_LAYER_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "region": _region_metadata(normalized_structures),
        "strict": bool(strict),
        "release_gate_status": "passed" if not blockers else "failed",
        "release_gate_blockers": blockers,
        "assignment": assignment,
        "source_lineage": _source_lineage(normalized_structures),
        "limitations": [
            "Ward exposure aggregates only assigned structures.",
            "Missing structure attributes are reported as completeness gaps and are not inferred.",
            "Hazard probabilities, flood extents, and official impact claims are outside this layer.",
        ],
    }
    return {"metadata": json_safe(metadata), "wards": json_safe(ward_features)}


def _ward_overlap_diagnostics(wards: gpd.GeoDataFrame, ward_id_column: str) -> dict:
    """Measure positive-area ward overlaps in a locally estimated projected CRS."""
    projected = wards.to_crs(wards.estimate_utm_crs() or "EPSG:3857").reset_index(drop=True)
    pairs = gpd.sjoin(
        projected[[ward_id_column, "geometry"]],
        projected[[ward_id_column, "geometry"]],
        how="inner",
        predicate="intersects",
        lsuffix="left",
        rsuffix="right",
    )
    pairs = pairs[pairs.index < pairs["index_right"]]
    areas: list[float] = []
    examples: list[dict[str, Any]] = []
    for left_index, row in pairs.iterrows():
        area = float(
            projected.loc[left_index].geometry.intersection(
                projected.loc[row["index_right"]].geometry
            ).area
        )
        if area <= 1e-6:
            continue
        areas.append(area)
        if len(examples) < 20:
            examples.append(
                {
                    "left_ward": str(projected.loc[left_index, ward_id_column]),
                    "right_ward": str(projected.loc[row["index_right"], ward_id_column]),
                    "overlap_area_m2": area,
                }
            )
    return {
        "overlap_pair_count": len(areas),
        "total_overlap_area_m2": float(sum(areas)),
        "max_overlap_area_m2": float(max(areas, default=0.0)),
        "examples": examples,
    }


def write_ward_structure_exposure(payload: dict, path: Path) -> Path:
    """Write a compact JSON structure exposure artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True))
    return path


def _ward_feature(ward_no: str, group: gpd.GeoDataFrame) -> dict:
    """Build one ward exposure record from known values only."""
    type_counts = _structure_type_counts(group)
    return {
        "ward_no": ward_no,
        "structure_count": int(len(group)),
        "residential_structure_count": type_counts["residential"],
        "public_structure_count": type_counts["public"],
        "commercial_structure_count": type_counts["commercial"],
        "unknown_structure_type_count": type_counts["unknown"],
        "total_footprint_area_m2": _numeric_sum(group, "FootprintArea_m2"),
        "total_footprint_area_sqft": _numeric_sum(group, "FootprintArea_sqft"),
        "known_units_total": _numeric_sum(group, "NumUnits"),
        "known_occupant_count_total": _numeric_sum(group, "OccupantCount"),
        "known_num_stories_average": _numeric_mean(group, "NumStories"),
        "known_num_stories_max": _numeric_max(group, "NumStories"),
        "attribute_completeness": {
            "structure_type": _completeness(group, "StructureType"),
            "num_stories": _completeness(group, "NumStories"),
            "num_units": _completeness(group, "NumUnits"),
            "occupant_count": _completeness(group, "OccupantCount"),
        },
        "datasource_completeness": {
            source_column: _completeness(group, source_column)
            for source_column in CORE_ATTRIBUTE_SOURCES.values()
        },
        "source_counts": _source_counts(group),
        "coverage_tiers": sorted(_present_values(group, "CoverageTier")),
        "data_refresh_timestamp": _max_text(group, "data_refresh_timestamp"),
        "last_refreshed": _max_text(group, "last_refreshed"),
        "source_as_of": _max_text(group, "source_as_of"),
        "feature_basis": "Canonical structures assigned to ward polygons by representative point; no hazard inference is performed.",
    }


def _structure_type_counts(group: gpd.GeoDataFrame) -> Counter:
    counts: Counter = Counter({"residential": 0, "public": 0, "commercial": 0, "unknown": 0})
    for value in group.get("StructureType", pd.Series(dtype="object")).fillna("").astype(str):
        normalized = value.strip().lower()
        matched = False
        for label, aliases in TYPE_GROUPS.items():
            if normalized in aliases:
                counts[label] += 1
                matched = True
                break
        if not matched:
            counts["unknown"] += 1
    return counts


def _source_counts(group: gpd.GeoDataFrame) -> dict[str, dict[str, int]]:
    return {
        column: dict(Counter(_present_list(group, column)))
        for column in ("RawDataSource", "LoadSource", "FootprintSource")
    }


def _source_lineage(structures: gpd.GeoDataFrame) -> dict:
    return {
        "raw_data_sources": sorted(_present_values(structures, "RawDataSource")),
        "load_sources": sorted(_present_values(structures, "LoadSource")),
        "footprint_sources": sorted(_present_values(structures, "FootprintSource")),
        "attribute_source_columns": dict(CORE_ATTRIBUTE_SOURCES),
        "data_refresh_timestamp": _max_text(structures, "data_refresh_timestamp"),
        "source_as_of": _max_text(structures, "source_as_of"),
    }


def _region_metadata(structures: gpd.GeoDataFrame) -> dict:
    return {
        "city": _single_or_mixed(structures, "City"),
        "state": _single_or_mixed(structures, "State"),
        "country": _single_or_mixed(structures, "Country"),
    }


def _present(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip() != ""


def _present_values(group: pd.DataFrame, column: str) -> set[str]:
    return set(_present_list(group, column))


def _present_list(group: pd.DataFrame, column: str) -> list[str]:
    if column not in group.columns or group.empty:
        return []
    return [str(value).strip() for value in group[column].tolist() if _present(value)]


def _ward_sort_key(value: str) -> tuple[int, int | str]:
    text = value.strip()
    return (0, int(text)) if text.isdigit() else (1, text)


def _single_or_mixed(group: pd.DataFrame, column: str) -> str | None:
    values = sorted(_present_values(group, column))
    if not values:
        return None
    return values[0] if len(values) == 1 else "mixed"


def _max_text(group: pd.DataFrame, column: str) -> str | None:
    values = sorted(_present_values(group, column))
    return values[-1] if values else None


def _completeness(group: pd.DataFrame, column: str) -> float:
    if group.empty or column not in group.columns:
        return 0.0
    return round(sum(1 for value in group[column].tolist() if _present(value)) / len(group), 4)


def _numeric_series(group: pd.DataFrame, column: str) -> pd.Series:
    if group.empty or column not in group.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(group[column], errors="coerce").dropna()


def _numeric_sum(group: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(group, column)
    return round(float(values.sum()), 4) if not values.empty else None


def _numeric_mean(group: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(group, column)
    return round(float(values.mean()), 4) if not values.empty else None


def _numeric_max(group: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(group, column)
    return round(float(values.max()), 4) if not values.empty else None
