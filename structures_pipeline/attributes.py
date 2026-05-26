from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from structures_pipeline.constants import (
    MICROSOFT_DATASET_LINKS_URL,
    NSI_STRUCTURES_URL,
    REQUIRED_OUTPUT_COLUMNS,
)
from structures_pipeline.geometry import add_area_columns
from structures_pipeline.utils import combine_first_with_source, confidence_for_source, to_numeric_safe


def normalize_structure_type(raw: pd.Series) -> pd.Series:
    text = raw.fillna("").astype(str).str.lower()
    result = pd.Series(pd.NA, index=raw.index, dtype="object")
    rules = [
        (r"condo|condominium", "condo"),
        (r"apart|res3|multi.?family|multifamily", "apartment"),
        (r"hotel|motel|res4", "hotel"),
        (r"garage|parking", "garage"),
        (r"barn|farm_auxiliary|agric|stable|greenhouse", "barn"),
        (r"mobile|manufactured|res2", "mobile_home"),
        (r"school|college|university|edu", "education"),
        (r"hospital|clinic|medical|nursing|res6", "healthcare"),
        (r"warehouse|wholesale|com2", "warehouse"),
        (r"industrial|factory|ind", "industrial"),
        (r"retail|office|commercial|com", "commercial"),
        (r"church|civic|public|government|religious", "public"),
        (r"house|detached|semidetached|terrace|residential|res1|res", "residential"),
    ]
    for pattern, label in rules:
        mask = result.isna() & text.str.contains(pattern, regex=True, na=False)
        result.loc[mask] = label
    return result


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA


def finalize_attributes(
    base: gpd.GeoDataFrame,
    place: pd.Series,
    census_household_size: float | None,
    acs_source: str | None,
    overture_release: str | None,
    census_year: int,
) -> gpd.GeoDataFrame:
    if base.empty:
        for column in REQUIRED_OUTPUT_COLUMNS:
            if column != "geometry":
                base[column] = pd.Series(dtype="object")
        return base[REQUIRED_OUTPUT_COLUMNS]

    out = add_area_columns(base.copy())
    out["PlaceGEOID"] = str(place["PlaceGEOID"])
    out["City"] = place["City"]
    out["State"] = place["State"]
    out["StateFP"] = place["StateFP"]
    out["Country"] = "USA"

    _ensure_columns(
        out,
        [
            "OSM_StructureType",
            "OvertureClass",
            "OvertureSubtype",
            "NSI_OccType",
            "NSI_DamageCategory",
            "ParcelLandUse",
            "SQLStructureType",
            "Units_OSM",
            "NSI_ResUnits",
            "Stories_OSM",
            "Stories_OVT",
            "NSI_NumStory",
            "SQLStories",
            "Height_OSM",
            "Height_OVT",
            "Height_MS",
            "SQLHeight",
            "NSI_Pop2AM",
            "NSI_Pop2PM",
            "NSI_EmpNum",
            "NSI_Students",
        ],
    )

    out["StructureTypeRaw"], out["StructureTypeSource"] = combine_first_with_source(
        out,
        [
            ("OSM_StructureType", "osm"),
            ("OvertureClass", "overture_class"),
            ("OvertureSubtype", "overture_subtype"),
            ("NSI_OccType", "nsi_occtype"),
            ("NSI_DamageCategory", "nsi_damage_category"),
            ("ParcelLandUse", "parcel_land_use"),
            ("SQLStructureType", "sql_structure_type"),
        ],
    )
    out["StructureType"] = normalize_structure_type(out["StructureTypeRaw"])
    out["StructureTypeConfidence"] = confidence_for_source(
        out["StructureTypeSource"],
        {
            "osm": 0.85,
            "overture_class": 0.80,
            "overture_subtype": 0.78,
            "nsi_occtype": 0.72,
            "nsi_damage_category": 0.68,
            "parcel_land_use": 0.62,
            "sql_structure_type": 0.70,
        },
    )

    height, height_source = combine_first_with_source(
        out,
        [("Height_OSM", "osm"), ("Height_OVT", "overture"), ("Height_MS", "microsoft"), ("SQLHeight", "sql")],
    )
    out["HeightM"] = to_numeric_safe(height, index=out.index)
    out["HeightSource"] = height_source
    out["Stories_EstFromHeight"] = (out["HeightM"] / 3.05).round().clip(lower=1, upper=200)
    out.loc[out["HeightM"].isna(), "Stories_EstFromHeight"] = np.nan

    out["NumStories"], out["NumStoriesSource"] = combine_first_with_source(
        out,
        [
            ("Stories_OSM", "osm"),
            ("Stories_OVT", "overture"),
            ("NSI_NumStory", "nsi"),
            ("SQLStories", "sql"),
            ("Stories_EstFromHeight", "height_estimate"),
        ],
    )
    out["NumStories"] = to_numeric_safe(out["NumStories"], index=out.index)
    out["NumStoriesConfidence"] = confidence_for_source(
        out["NumStoriesSource"],
        {"osm": 0.90, "overture": 0.86, "nsi": 0.78, "sql": 0.74, "height_estimate": 0.55},
    )

    out["NumUnits"], out["NumUnitsSource"] = combine_first_with_source(
        out,
        [("Units_OSM", "osm"), ("NSI_ResUnits", "nsi")],
    )
    out["NumUnits"] = to_numeric_safe(out["NumUnits"], index=out.index)
    infer_single = (
        out["NumUnits"].isna()
        & out["StructureType"].isin(["residential", "mobile_home"])
        & out["StructureTypeRaw"].fillna("").astype(str).str.lower().str.contains(
            r"house|detached|semidetached|terrace|res1|res2|mobile", regex=True
        )
    )
    out.loc[infer_single, "NumUnits"] = 1
    out.loc[infer_single, "NumUnitsSource"] = "inferred_single_family"
    out["NumUnitsConfidence"] = confidence_for_source(
        out["NumUnitsSource"],
        {"osm": 0.90, "nsi": 0.78, "inferred_single_family": 0.58},
    )

    nsi_people = pd.concat(
        [
            to_numeric_safe(out.get("NSI_Pop2AM"), index=out.index),
            to_numeric_safe(out.get("NSI_Pop2PM"), index=out.index),
            (
                to_numeric_safe(out.get("NSI_EmpNum"), index=out.index).fillna(0)
                + to_numeric_safe(out.get("NSI_Students"), index=out.index).fillna(0)
            ).replace(0, np.nan),
        ],
        axis=1,
    ).max(axis=1, skipna=True)
    out["OccupantCount"] = nsi_people
    out["OccupantCountSource"] = np.where(nsi_people.notna(), "nsi", pd.NA)
    out["OccupantCountMethod"] = np.where(
        nsi_people.notna(), "nsi_max_2am_2pm_emp_students", pd.NA
    )
    out["OccupantCountConfidence"] = np.where(nsi_people.notna(), 0.76, np.nan)

    if census_household_size is not None:
        census_est = out["NumUnits"] * census_household_size
        census_mask = (
            out["OccupantCount"].isna()
            & out["StructureType"].isin(["residential", "condo", "apartment", "mobile_home"])
            & census_est.notna()
        )
        out.loc[census_mask, "OccupantCount"] = census_est.loc[census_mask]
        out.loc[census_mask, "OccupantCountSource"] = "acs"
        out.loc[census_mask, "OccupantCountMethod"] = "num_units_x_acs_household_size"
        out.loc[census_mask, "OccupantCountConfidence"] = 0.52

    out["OvertureRelease"] = overture_release
    out["CensusYear"] = census_year
    out["ACSSource"] = acs_source
    out["NSISource"] = NSI_STRUCTURES_URL
    out["MicrosoftSource"] = MICROSOFT_DATASET_LINKS_URL

    for column in REQUIRED_OUTPUT_COLUMNS:
        if column not in out.columns:
            out[column] = pd.NA
    return out[REQUIRED_OUTPUT_COLUMNS].to_crs(epsg=4326).reset_index(drop=True)
