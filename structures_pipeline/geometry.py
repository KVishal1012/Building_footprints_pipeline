from __future__ import annotations

from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon

from structures_pipeline.constants import SQM_TO_SQFT


# Create an empty GeoDataFrame with a known geometry column and CRS.
def empty_gdf(columns: Iterable[str] = (), crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    """Create an empty GeoDataFrame with a known geometry column and CRS."""
    return gpd.GeoDataFrame({column: [] for column in columns}, geometry=[], crs=crs)


# Extract polygonal geometry from mixed/collection inputs and drop lines/points.
def polygonal_part(geometry):
    """Extract polygonal geometry from mixed/collection inputs and drop lines/points."""
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    if geometry.geom_type != "GeometryCollection":
        return None
    polygons = []
    for part in geometry.geoms:
        polygonal = polygonal_part(part)
        if polygonal is None:
            continue
        if polygonal.geom_type == "Polygon":
            polygons.append(polygonal)
        else:
            polygons.extend(polygonal.geoms)
    if not polygons:
        return None
    return polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)


# Remove empty/invalid geometries and keep only valid polygons or multipolygons.
def clean_geom(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Remove empty/invalid geometries and keep only valid polygons or multipolygons."""
    if gdf.empty:
        return gdf
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    geometry_column = gdf.geometry.name
    cleaned = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if cleaned.empty:
        return cleaned
    invalid = ~cleaned.geometry.is_valid
    if invalid.any():
        cleaned.loc[invalid, geometry_column] = cleaned.loc[
            invalid, geometry_column
        ].make_valid()
    cleaned[geometry_column] = cleaned.geometry.apply(polygonal_part)
    cleaned = cleaned[
        cleaned.geometry.notna()
        & ~cleaned.geometry.is_empty
        & cleaned.geometry.is_valid
        & cleaned.geometry.geom_type.isin({"Polygon", "MultiPolygon"})
    ].copy()
    return cleaned.reset_index(drop=True)


# Return a single clean EPSG:4326 boundary polygon for source clipping.
def normalize_boundary(boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return a single clean EPSG:4326 boundary polygon for source clipping."""
    if boundary.empty:
        return empty_gdf()
    if boundary.crs is None:
        boundary = boundary.set_crs(epsg=4326)
    boundary = clean_geom(boundary.to_crs(epsg=4326))
    if boundary.empty:
        return boundary
    if len(boundary) > 1:
        unioned = (
            boundary.geometry.union_all()
            if hasattr(boundary.geometry, "union_all")
            else boundary.geometry.unary_union
        )
        boundary = gpd.GeoDataFrame(geometry=[unioned], crs="EPSG:4326")
    return clean_geom(boundary).reset_index(drop=True)


# Return total bounds as plain floats for APIs that reject numpy scalars.
def bounds_tuple(gdf: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    """Return total bounds as plain floats for APIs that reject numpy scalars."""
    minx, miny, maxx, maxy = gdf.total_bounds
    return float(minx), float(miny), float(maxx), float(maxy)


# Pick a local projected CRS from available data, falling back to CONUS Albers.
def estimated_projected_crs(*gdfs: gpd.GeoDataFrame):
    """Pick a local projected CRS from available data, falling back to CONUS Albers."""
    for gdf in gdfs:
        if gdf is not None and not gdf.empty:
            crs = gdf.estimate_utm_crs()
            if crs is not None:
                return crs
    return "EPSG:5070"


# Add footprint area in square meters and square feet using a projected CRS.
def add_area_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add footprint area in square meters and square feet using a projected CRS."""
    out = gdf.copy()
    if out.empty:
        out["FootprintArea_m2"] = pd.Series(dtype="float64")
        out["FootprintArea_sqft"] = pd.Series(dtype="float64")
        return out
    work_crs = estimated_projected_crs(out)
    area_m2 = out.to_crs(work_crs).geometry.area
    out["FootprintArea_m2"] = area_m2.to_numpy()
    out["FootprintArea_sqft"] = out["FootprintArea_m2"] * SQM_TO_SQFT
    return out


# Assign buildings to one place while preserving original footprint geometry.
def assign_footprints_to_place(
    footprints: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    min_overlap_ratio: float = 0.0,
) -> gpd.GeoDataFrame:
    """Assign buildings to one place while preserving original footprint geometry."""
    if footprints.empty:
        return footprints.copy()
    footprints = clean_geom(footprints.to_crs(boundary.crs)).reset_index(drop=True)
    boundary = normalize_boundary(boundary)
    if footprints.empty or boundary.empty:
        return footprints.iloc[0:0].copy()

    place_geom = boundary.geometry.iloc[0]
    rep_points = footprints.geometry.representative_point()
    rep_mask = rep_points.apply(place_geom.covers)

    assigned = footprints.loc[rep_mask].copy()
    assigned["FootprintAssignmentMethod"] = "representative_point_within"
    assigned["FootprintAssignmentOverlapRatio"] = np.nan

    remaining = footprints.loc[~rep_mask & footprints.geometry.intersects(place_geom)].copy()
    if remaining.empty:
        return assigned.reset_index(drop=True)

    work_crs = estimated_projected_crs(remaining, boundary)
    rem_proj = remaining.to_crs(work_crs)
    boundary_geom = boundary.to_crs(work_crs).geometry.iloc[0]
    area = rem_proj.geometry.area.replace(0, np.nan)
    overlap_area = rem_proj.geometry.intersection(boundary_geom).area
    ratio = overlap_area / area
    overlap_mask = (overlap_area > 0) & ratio.fillna(0).ge(min_overlap_ratio)
    overlap = remaining.loc[overlap_mask].copy()
    overlap["FootprintAssignmentMethod"] = "largest_boundary_overlap"
    overlap["FootprintAssignmentOverlapRatio"] = ratio.loc[overlap_mask].to_numpy()
    return gpd.GeoDataFrame(
        pd.concat([assigned, overlap], ignore_index=True),
        geometry="geometry",
        crs=footprints.crs,
    ).reset_index(drop=True)


# Remove fallback footprints already covered by primary source footprints.
def dedupe_fallback_footprints(
    primary: gpd.GeoDataFrame,
    fallback: gpd.GeoDataFrame,
    overlap_ratio_threshold: float,
) -> gpd.GeoDataFrame:
    """Remove fallback footprints already covered by primary source footprints."""
    if fallback.empty or primary.empty:
        return fallback.reset_index(drop=True)
    primary = clean_geom(primary.to_crs(epsg=4326))
    fallback = clean_geom(fallback.to_crs(epsg=4326)).reset_index(drop=True)
    if fallback.empty or primary.empty:
        return fallback

    points = fallback[["geometry"]].copy()
    points["_FallbackIndex"] = fallback.index
    points["geometry"] = fallback.geometry.representative_point()
    point_join = gpd.sjoin(
        points,
        primary[["geometry"]],
        how="left",
        predicate="within",
    )
    duplicate_indexes = set(
        point_join.loc[point_join["index_right"].notna(), "_FallbackIndex"].astype(int)
    )

    work_crs = estimated_projected_crs(primary, fallback)
    left = fallback.to_crs(work_crs).copy()
    right = primary.to_crs(work_crs).copy()
    left["_FallbackIndex"] = left.index
    left["_FallbackArea_m2"] = left.geometry.area.replace(0, np.nan)
    joined = gpd.sjoin(
        left[["_FallbackIndex", "_FallbackArea_m2", "geometry"]],
        right[["geometry"]],
        how="inner",
        predicate="intersects",
    )
    if not joined.empty:
        right_geoms = gpd.GeoSeries(
            right.geometry.iloc[joined["index_right"].to_numpy()].to_numpy(),
            index=joined.index,
            crs=work_crs,
        )
        joined["_OverlapRatio"] = (
            joined.geometry.intersection(right_geoms).area / joined["_FallbackArea_m2"]
        )
        overlap_dupes = joined.loc[
            joined["_OverlapRatio"].fillna(0) >= overlap_ratio_threshold,
            "_FallbackIndex",
        ].astype(int)
        duplicate_indexes.update(overlap_dupes.tolist())

    keep = ~fallback.index.isin(duplicate_indexes)
    return fallback.loc[keep].reset_index(drop=True)


# Cheaply reduce candidate rows to the boundary bounding box before spatial ops.
def clip_candidates_to_bbox(gdf: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Cheaply reduce candidate rows to the boundary bounding box before spatial ops."""
    if gdf.empty:
        return gdf
    minx, miny, maxx, maxy = bounds_tuple(boundary)
    return gdf.cx[minx:maxx, miny:maxy].copy()


# Clean geometries, retrying with fixed precision when GEOS raises robustness errors.
def validate_geometry_or_empty(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Clean geometries, retrying with fixed precision when GEOS raises robustness errors."""
    try:
        return clean_geom(gdf)
    except GEOSException:
        precise = gdf.copy()
        precise[precise.geometry.name] = precise.geometry.set_precision(1e-9)
        return clean_geom(precise)
