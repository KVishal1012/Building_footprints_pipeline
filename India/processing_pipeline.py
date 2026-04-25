from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt

from pipeline_utils import (
    clean_geometry as shared_clean_geometry,
    estimated_projected_crs,
    normalize_alias_name,
    normalize_field_name,
    resolve_source_path as shared_resolve_source_path,
    slugify as shared_slugify,
    source_failure as shared_source_failure,
    write_metadata_sidecar as shared_write_metadata_sidecar,
)


PROCESSING_LAYER_TYPES = {
    "segmentation",
    "change_detection",
    "flood_prediction",
    "urban_planning",
    "planning_context",
    "custom",
}

PROCESSING_LAYER_COLUMNS = [
    "LayerID",
    "LayerType",
    "City",
    "State",
    "Country",
    "SourceName",
    "SourceAuthority",
    "SourcePath",
    "ModelFamily",
    "ModelName",
    "ModelVersion",
    "Task",
    "RunID",
    "RunTimestamp",
    "Label",
    "Score",
    "Value",
    "DateFrom",
    "DateTo",
    "Scenario",
    "HorizonHours",
    "DepthM",
    "Probability",
    "geometry",
]

PROCESSING_LINK_COLUMNS = [
    "StructureID",
    "LayerID",
    "LayerType",
    "City",
    "State",
    "Country",
    "SourceName",
    "SourceAuthority",
    "ModelFamily",
    "ModelName",
    "ModelVersion",
    "Task",
    "RunID",
    "RunTimestamp",
    "Label",
    "Score",
    "Value",
    "DateFrom",
    "DateTo",
    "Scenario",
    "HorizonHours",
    "DepthM",
    "Probability",
    "MatchMethod",
    "MatchArea_m2",
    "StructureCoverage",
    "LayerCoverage",
]

FIELD_ALIASES = {
    "Label": [
        "label",
        "class",
        "class_name",
        "prediction",
        "predicted_class",
        "risk",
        "flood_risk",
        "planning_label",
        "suitability",
        "change_type",
    ],
    "Score": ["score", "confidence", "probability_score", "risk_score"],
    "Value": ["value", "class_value", "pixel_value", "category_value"],
    "DateFrom": ["date_from", "from_date", "before_date", "start_date"],
    "DateTo": ["date_to", "to_date", "after_date", "end_date"],
    "Scenario": ["scenario", "event", "case_name"],
    "HorizonHours": ["horizon_hr", "horizon_hours", "forecast_horizon_hr"],
    "DepthM": ["depth_m", "flood_depth_m", "depth"],
    "Probability": ["probability", "flood_probability", "prob"],
}

STATE_ABBR_TO_NAME = {
    "KA": "Karnataka",
    "MH": "Maharashtra",
    "TN": "Tamil Nadu",
    "TG": "Telangana",
    "TS": "Telangana",
}


@dataclass
class ProcessingConfig:
    data_dir: Path = field(default_factory=lambda: MODULE_DIR / "data")
    structure_path: Path = field(
        default_factory=lambda: MODULE_DIR / "data/output/structures_master.parquet"
    )
    output_dir: Path = field(default_factory=lambda: MODULE_DIR / "data/processing/output")
    raw_dir: Path = field(default_factory=lambda: MODULE_DIR / "data/processing/raw")
    country: str = "India"
    strict_sources: bool = False
    write_run_metadata: bool = True
    min_intersection_area_m2: float = 1.0
    enforce_crs: bool = True
    enforce_geometry_non_empty: bool = True
    enforce_field_map_columns: bool = True
    max_null_scenario_rate: float = 0.05
    metrics_output_path: Path | None = None

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.structure_path = Path(self.structure_path)
        self.output_dir = Path(self.output_dir)
        self.raw_dir = Path(self.raw_dir)
        if self.metrics_output_path is not None:
            self.metrics_output_path = Path(self.metrics_output_path)
        else:
            self.metrics_output_path = self.output_dir / "processing_metrics.json"
        self.validate()

    def validate(self) -> None:
        if not str(self.country).strip():
            raise ValueError("country must not be empty")
        if self.min_intersection_area_m2 < 0:
            raise ValueError("min_intersection_area_m2 must not be negative")
        if not 0 <= self.max_null_scenario_rate <= 1:
            raise ValueError("max_null_scenario_rate must be between 0 and 1")

    def ensure_dirs(self) -> None:
        for path in (self.output_dir, self.raw_dir):
            path.mkdir(parents=True, exist_ok=True)
        if self.metrics_output_path is not None:
            self.metrics_output_path.parent.mkdir(parents=True, exist_ok=True)


def slugify(*parts: str) -> str:
    return shared_slugify(*parts, fallback="layer")


def normalize_state_name(state: str | None) -> str | None:
    return normalize_alias_name(state, STATE_ABBR_TO_NAME, collapse_alias_key=True)


def normalize_layer_type(value: str) -> str:
    layer_type = slugify(value)
    if layer_type not in PROCESSING_LAYER_TYPES:
        raise ValueError(
            f"Unsupported layer_type={value!r}. "
            f"Use one of {sorted(PROCESSING_LAYER_TYPES)}."
        )
    return layer_type


def find_column(gdf: gpd.GeoDataFrame, source: dict, canonical_name: str) -> str | None:
    field_map = source.get("field_map", {})
    configured = field_map.get(canonical_name) or field_map.get(
        re.sub(r"(?<!^)(?=[A-Z])", "_", canonical_name).lower()
    )
    candidates = []
    if configured:
        candidates.extend(configured if isinstance(configured, list) else [configured])
    candidates.extend(FIELD_ALIASES.get(canonical_name, []))

    lookup = {normalize_field_name(column): column for column in gdf.columns}
    for candidate in candidates:
        column = lookup.get(normalize_field_name(candidate))
        if column:
            return column
    return None


def resolve_source_path(path_value: str | Path, config: ProcessingConfig) -> Path:
    path = Path(path_value).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([config.raw_dir / path, config.data_dir / path, Path.cwd() / path])
        candidates.append(MODULE_DIR / path)
    return shared_resolve_source_path(path, candidates, fallback=candidates[0]).resolve()


def source_failure(message: str, config: ProcessingConfig, exc: Exception | None = None) -> None:
    shared_source_failure(message, strict=config.strict_sources, exc=exc)


def empty_processing_layers(crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(columns=PROCESSING_LAYER_COLUMNS, geometry="geometry", crs=crs)


def empty_processing_links() -> pd.DataFrame:
    return pd.DataFrame(columns=PROCESSING_LINK_COLUMNS)


def clean_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return shared_clean_geometry(gdf, validate_all=True)


def read_table_source(path: Path, source: dict) -> gpd.GeoDataFrame:
    sep = "\t" if path.suffix.lower() == ".tsv" else ","
    table = pd.read_csv(path, sep=sep)
    geometry_column = source.get("geometry_column", "geometry")
    wkt_column = source.get("wkt_column")
    lon_column = source.get("longitude_column") or source.get("lon_column")
    lat_column = source.get("latitude_column") or source.get("lat_column")

    if wkt_column and wkt_column in table:
        geometry = table[wkt_column].map(wkt.loads)
    elif geometry_column in table:
        geometry = table[geometry_column].map(wkt.loads)
    elif lon_column in table and lat_column in table:
        geometry = gpd.points_from_xy(table[lon_column], table[lat_column])
    else:
        raise ValueError(
            f"{path} must include WKT geometry or longitude/latitude columns."
        )
    return gpd.GeoDataFrame(table, geometry=geometry, crs=source.get("crs", "EPSG:4326"))


def read_processing_source(source: dict, config: ProcessingConfig) -> gpd.GeoDataFrame:
    if "path" not in source:
        source_failure("Processing source skipped: missing 'path'", config)
        return empty_processing_layers()
    path = resolve_source_path(source["path"], config)
    if not path.exists():
        source_failure(f"Processing source skipped: file not found at {path}", config)
        return empty_processing_layers()

    suffix = path.suffix.lower()
    if suffix in {".parquet", ".geoparquet"}:
        gdf = gpd.read_parquet(path)
    elif suffix in {".csv", ".tsv"}:
        gdf = read_table_source(path, source)
    else:
        gdf = gpd.read_file(path)

    if gdf.crs is None:
        if config.enforce_crs:
            raise ValueError(f"Processing source {path} is missing CRS")
        gdf = gdf.set_crs(source.get("crs", "EPSG:4326"))

    if config.enforce_field_map_columns:
        field_map = source.get("field_map", {}) or {}
        normalized = {normalize_field_name(column): column for column in gdf.columns}
        for canonical_name, mapped in field_map.items():
            candidates = mapped if isinstance(mapped, list) else [mapped]
            found = False
            for candidate in candidates:
                if normalize_field_name(str(candidate)) in normalized:
                    found = True
                    break
            if not found:
                raise ValueError(
                    f"Processing source {path} field_map requires missing column for "
                    f"{canonical_name}: {mapped}"
                )

    original_row_count = len(gdf)
    cleaned = clean_geometry(gdf.to_crs(epsg=4326))
    if config.enforce_geometry_non_empty and original_row_count > 0 and cleaned.empty:
        raise ValueError(f"Processing source {path} has no valid geometries after cleanup")
    return cleaned


def scalar_source_value(source: dict, *keys: str, default=None):
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


def standardize_processing_layer(
    raw: gpd.GeoDataFrame, source: dict, config: ProcessingConfig | None = None
) -> gpd.GeoDataFrame:
    config = config or ProcessingConfig()
    if raw.empty:
        return empty_processing_layers()

    layer_type = normalize_layer_type(source.get("layer_type", "custom"))
    city = scalar_source_value(source, "city")
    state = normalize_state_name(scalar_source_value(source, "state"))
    source_name = scalar_source_value(source, "source_name", "name", default=layer_type)
    source_path = str(scalar_source_value(source, "path", default=""))
    run_id = scalar_source_value(source, "run_id", default=slugify(source_name, datetime.now(timezone.utc).date()))
    run_timestamp = scalar_source_value(
        source, "run_timestamp", default=datetime.now(timezone.utc).isoformat()
    )

    raw = clean_geometry(raw.to_crs(epsg=4326)).reset_index(drop=True)
    out = gpd.GeoDataFrame(index=raw.index, geometry=raw.geometry, crs="EPSG:4326")
    out["LayerID"] = [
        f"{slugify(city or config.country, layer_type, source_name, run_id)}_{i:08d}"
        for i in range(len(raw))
    ]
    out["LayerType"] = layer_type
    out["City"] = city
    out["State"] = state
    out["Country"] = scalar_source_value(source, "country", default=config.country)
    out["SourceName"] = source_name
    out["SourceAuthority"] = scalar_source_value(source, "source_authority", "authority")
    out["SourcePath"] = source_path
    out["ModelFamily"] = scalar_source_value(source, "model_family")
    out["ModelName"] = scalar_source_value(source, "model_name", "model_id", "model")
    out["ModelVersion"] = scalar_source_value(source, "model_version", "version")
    out["Task"] = scalar_source_value(source, "task", default=layer_type)
    out["RunID"] = run_id
    out["RunTimestamp"] = run_timestamp

    for canonical in (
        "Label",
        "Score",
        "Value",
        "DateFrom",
        "DateTo",
        "Scenario",
        "HorizonHours",
        "DepthM",
        "Probability",
    ):
        column = find_column(raw, source, canonical)
        out[canonical] = raw[column] if column else scalar_source_value(source, canonical)

    for numeric_column in ("Score", "HorizonHours", "DepthM", "Probability"):
        out[numeric_column] = pd.to_numeric(out[numeric_column], errors="coerce")
    for text_column in ("Label", "Value", "Scenario"):
        out[text_column] = out[text_column].astype("string")

    return out[PROCESSING_LAYER_COLUMNS].reset_index(drop=True)


def load_processing_layers(
    sources: list[dict], config: ProcessingConfig | None = None
) -> gpd.GeoDataFrame:
    config = config or ProcessingConfig()
    layers = []
    for source in sources:
        raw = read_processing_source(source, config)
        layers.append(standardize_processing_layer(raw, source, config))
    if not layers:
        return empty_processing_layers()
    return gpd.GeoDataFrame(
        pd.concat(layers, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )


def load_structures(config: ProcessingConfig) -> gpd.GeoDataFrame:
    structure_path = resolve_source_path(config.structure_path, config)
    if not structure_path.exists():
        source_failure(f"Structure file not found at {structure_path}", config)
        return gpd.GeoDataFrame(columns=["StructureID", "geometry"], geometry="geometry", crs="EPSG:4326")
    structures = gpd.read_parquet(structure_path)
    if "StructureID" not in structures.columns:
        raise ValueError(f"{structure_path} is missing StructureID")
    return clean_geometry(structures.to_crs(epsg=4326))


def matching_crs(*gdfs: gpd.GeoDataFrame):
    return estimated_projected_crs(*gdfs, fallback="EPSG:6933")


def link_processing_layers_to_structures(
    structures: gpd.GeoDataFrame,
    layers: gpd.GeoDataFrame,
    config: ProcessingConfig | None = None,
) -> pd.DataFrame:
    config = config or ProcessingConfig()
    if structures.empty or layers.empty:
        return empty_processing_links()

    structures = clean_geometry(structures.to_crs(epsg=4326))
    layers = clean_geometry(layers.to_crs(epsg=4326))
    if "StructureID" not in structures.columns:
        raise ValueError("structures must include StructureID")
    missing_layer_columns = [
        column for column in PROCESSING_LAYER_COLUMNS if column not in layers.columns
    ]
    if missing_layer_columns:
        raise ValueError(f"layers missing columns: {missing_layer_columns}")

    projected_crs = matching_crs(structures, layers)
    structures_projected = structures[["StructureID", "geometry"]].to_crs(projected_crs)
    layers_projected = layers.reset_index(drop=True).to_crs(projected_crs)

    point_mask = layers_projected.geom_type.isin(["Point", "MultiPoint"])
    layer_attrs = layers.drop(columns="geometry").reset_index(drop=True)
    link_frames = []

    if point_mask.any():
        joined = gpd.sjoin(
            layers_projected.loc[point_mask, ["geometry"]],
            structures_projected,
            how="inner",
            predicate="within",
        )
        if not joined.empty:
            point_links = pd.concat(
                [
                    joined[["StructureID"]].reset_index(drop=True),
                    layer_attrs.iloc[joined.index.to_numpy()].reset_index(drop=True),
                ],
                axis=1,
            )
            point_links["MatchMethod"] = "point_within_structure"
            point_links["MatchArea_m2"] = np.nan
            point_links["StructureCoverage"] = np.nan
            point_links["LayerCoverage"] = np.nan
            link_frames.append(point_links[PROCESSING_LINK_COLUMNS])

    area_layers = layers_projected.loc[~point_mask]
    if not area_layers.empty:
        joined = gpd.sjoin(
            structures_projected[["StructureID", "geometry"]],
            area_layers[["LayerID", "geometry"]],
            how="inner",
            predicate="intersects",
        )
        if not joined.empty:
            joined = joined.reset_index().rename(columns={"index": "structure_index"})
            structure_geoms = structures_projected.geometry.loc[
                joined["structure_index"].to_numpy()
            ].reset_index(drop=True)
            layer_geoms = area_layers.geometry.loc[
                joined["index_right"].to_numpy()
            ].reset_index(drop=True)
            intersections = structure_geoms.intersection(layer_geoms)
            match_area = intersections.area
            structure_area = structure_geoms.area.replace(0, np.nan)
            layer_area = layer_geoms.area.replace(0, np.nan)

            keep = match_area >= config.min_intersection_area_m2
            if keep.any():
                keep_values = keep.to_numpy()
                area_links = pd.concat(
                    [
                        joined.loc[keep_values, ["StructureID"]].reset_index(drop=True),
                        layer_attrs.iloc[
                            joined.loc[keep_values, "index_right"].to_numpy()
                        ].reset_index(drop=True),
                    ],
                    axis=1,
                )
                area_links["MatchMethod"] = "area_intersection"
                area_links["MatchArea_m2"] = match_area.loc[keep].to_numpy()
                area_links["StructureCoverage"] = (
                    match_area.loc[keep].to_numpy()
                    / structure_area.loc[keep].to_numpy()
                )
                area_links["LayerCoverage"] = (
                    match_area.loc[keep].to_numpy() / layer_area.loc[keep].to_numpy()
                )
                link_frames.append(area_links[PROCESSING_LINK_COLUMNS])

    if not link_frames:
        return empty_processing_links()
    return pd.concat(link_frames, ignore_index=True)[PROCESSING_LINK_COLUMNS]


def write_metadata_sidecar(path: Path, config: ProcessingConfig, metadata: dict) -> None:
    shared_write_metadata_sidecar(
        path,
        config,
        metadata,
        include_config=True,
        trailing_newline=True,
    )


def write_processing_outputs(
    layers: gpd.GeoDataFrame, links: pd.DataFrame, config: ProcessingConfig
) -> tuple[Path, Path]:
    config.ensure_dirs()
    layer_path = config.output_dir / "processing_layers.parquet"
    link_path = config.output_dir / "structure_processing_links.parquet"
    layers.to_parquet(layer_path, index=False)
    links.to_parquet(link_path, index=False)
    write_metadata_sidecar(
        layer_path,
        config,
        {
            "dataset": "processing_layers",
            "row_count": len(layers),
            "layer_type_counts": layers["LayerType"].value_counts(dropna=False).to_dict()
            if not layers.empty
            else {},
            "output_columns": PROCESSING_LAYER_COLUMNS,
        },
    )
    write_metadata_sidecar(
        link_path,
        config,
        {
            "dataset": "structure_processing_links",
            "row_count": len(links),
            "layer_type_counts": links["LayerType"].value_counts(dropna=False).to_dict()
            if not links.empty
            else {},
            "output_columns": PROCESSING_LINK_COLUMNS,
        },
    )
    return layer_path, link_path


def build_processing_metrics(
    layers: gpd.GeoDataFrame, links: pd.DataFrame, structures: gpd.GeoDataFrame
) -> dict:
    total_structures = int(len(structures))
    unique_linked_structures = int(links["StructureID"].nunique()) if not links.empty else 0
    link_rate = (
        float(unique_linked_structures / total_structures)
        if total_structures > 0
        else 0.0
    )

    scenario_layer_counts = (
        layers.groupby("Scenario", dropna=False)["LayerID"].count().to_dict()
        if not layers.empty
        else {}
    )
    scenario_link_counts = (
        links.groupby("Scenario", dropna=False)["StructureID"].count().to_dict()
        if not links.empty
        else {}
    )
    scenario_unique_structures = (
        links.groupby("Scenario", dropna=False)["StructureID"].nunique().to_dict()
        if not links.empty
        else {}
    )
    scenario_coverage = {}
    for scenario_key in set(scenario_layer_counts) | set(scenario_link_counts):
        linked_count = int(scenario_unique_structures.get(scenario_key, 0))
        scenario_coverage[str(scenario_key)] = {
            "layer_rows": int(scenario_layer_counts.get(scenario_key, 0)),
            "structure_links": int(scenario_link_counts.get(scenario_key, 0)),
            "unique_linked_structures": linked_count,
            "link_rate": float(linked_count / total_structures) if total_structures > 0 else 0.0,
        }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_layer_rows": int(len(layers)),
        "rows_by_source_name": layers["SourceName"].value_counts(dropna=False).to_dict()
        if not layers.empty
        else {},
        "rows_by_layer_type": layers["LayerType"].value_counts(dropna=False).to_dict()
        if not layers.empty
        else {},
        "rows_by_scenario": {str(k): int(v) for k, v in scenario_layer_counts.items()},
        "total_links": int(len(links)),
        "unique_linked_structures": unique_linked_structures,
        "total_structures": total_structures,
        "link_rate": link_rate,
        "scenario_coverage": scenario_coverage,
    }


def write_processing_metrics(metrics: dict, config: ProcessingConfig) -> Path:
    if config.metrics_output_path is None:
        raise ValueError("metrics_output_path must not be None")
    config.metrics_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.metrics_output_path.write_text(json.dumps(metrics, indent=2) + "\n")
    return config.metrics_output_path


def run_processing_pipeline(
    sources: list[dict], config: ProcessingConfig | None = None
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    config = config or ProcessingConfig()
    config.ensure_dirs()
    layers = load_processing_layers(sources, config)
    if not layers.empty:
        null_scenario_rate = float(layers["Scenario"].isna().mean())
        if null_scenario_rate > config.max_null_scenario_rate:
            raise ValueError(
                f"Scenario null rate {null_scenario_rate:.2%} exceeds "
                f"max_null_scenario_rate={config.max_null_scenario_rate:.2%}"
            )
    structures = load_structures(config)
    links = link_processing_layers_to_structures(structures, layers, config)
    layer_path, link_path = write_processing_outputs(layers, links, config)
    metrics = build_processing_metrics(layers, links, structures)
    metrics_path = write_processing_metrics(metrics, config)
    print(f"Saved {len(layers):,} processing layer rows to {layer_path}")
    print(f"Saved {len(links):,} structure-processing links to {link_path}")
    print(f"Saved processing metrics to {metrics_path}")
    print(
        "Processing metrics: "
        f"rows={metrics['total_layer_rows']:,}, "
        f"links={metrics['total_links']:,}, "
        f"linked_structures={metrics['unique_linked_structures']:,}, "
        f"link_rate={metrics['link_rate']:.2%}"
    )
    return layers, links


def read_source_config(path: Path) -> list[dict]:
    payload = json.loads(path.read_text())
    sources = payload.get("sources", payload) if isinstance(payload, dict) else payload
    if not isinstance(sources, list):
        raise ValueError("source config must be a list or an object with a 'sources' list")
    return sources


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build separate India ML/deep-learning processing layers."
    )
    parser.add_argument(
        "--source-config",
        required=False,
        type=Path,
        help="JSON file containing processing source specs.",
    )
    parser.add_argument(
        "--structure-path",
        default=MODULE_DIR / "data/output/structures_master.parquet",
        type=Path,
        help="Structure parquet from India/structure_pipeline.py.",
    )
    parser.add_argument("--data-dir", default=MODULE_DIR / "data", type=Path)
    parser.add_argument(
        "--raw-dir", default=MODULE_DIR / "data/processing/raw", type=Path
    )
    parser.add_argument(
        "--output-dir", default=MODULE_DIR / "data/processing/output", type=Path
    )
    parser.add_argument("--country", default="India")
    parser.add_argument("--strict-sources", action="store_true")
    parser.add_argument("--no-metadata", action="store_true")
    parser.add_argument("--min-intersection-area-m2", default=1.0, type=float)
    parser.add_argument("--max-null-scenario-rate", default=0.05, type=float)
    parser.add_argument("--disable-enforce-crs", action="store_true")
    parser.add_argument("--disable-enforce-geometry-non-empty", action="store_true")
    parser.add_argument("--disable-enforce-field-map-columns", action="store_true")
    parser.add_argument(
        "--metrics-output-path",
        type=Path,
        default=MODULE_DIR / "data/processing/output/processing_metrics.json",
    )
    parser.add_argument(
        "--report-metrics-only",
        action="store_true",
        help="Print metrics from existing outputs and exit.",
    )
    args = parser.parse_args()

    config = ProcessingConfig(
        data_dir=args.data_dir,
        structure_path=args.structure_path,
        output_dir=args.output_dir,
        raw_dir=args.raw_dir,
        country=args.country,
        strict_sources=args.strict_sources,
        write_run_metadata=not args.no_metadata,
        min_intersection_area_m2=args.min_intersection_area_m2,
        enforce_crs=not args.disable_enforce_crs,
        enforce_geometry_non_empty=not args.disable_enforce_geometry_non_empty,
        enforce_field_map_columns=not args.disable_enforce_field_map_columns,
        max_null_scenario_rate=args.max_null_scenario_rate,
        metrics_output_path=args.metrics_output_path,
    )
    if args.report_metrics_only:
        layers = gpd.read_parquet(config.output_dir / "processing_layers.parquet")
        links = pd.read_parquet(config.output_dir / "structure_processing_links.parquet")
        structures = load_structures(config)
        metrics = build_processing_metrics(layers, links, structures)
        print(json.dumps(metrics, indent=2))
        return

    if args.source_config is None:
        raise ValueError("--source-config is required unless --report-metrics-only is set")
    run_processing_pipeline(read_source_config(args.source_config), config)


if __name__ == "__main__":
    main()
