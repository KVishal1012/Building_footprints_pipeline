from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from structures_pipeline.config import PipelineConfig
from structures_pipeline.refresh import build_refresh_store, run_refresh_cycle
from structures_pipeline.utils import json_safe


# Load a prepared source file into a GeoDataFrame for local refresh runs.
def load_source_frame(path: Path) -> gpd.GeoDataFrame:
    """Load a prepared source file into a GeoDataFrame for local refresh runs."""
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return gpd.read_parquet(path)
    if suffix in {".geojson", ".json", ".gpkg", ".shp"}:
        return gpd.read_file(path)
    if suffix == ".csv":
        frame = pd.read_csv(path)
        if "geometry_wkt" not in frame.columns:
            raise ValueError("CSV refresh sources must include geometry_wkt")
        geometry = frame.pop("geometry_wkt").map(wkt.loads)
        return gpd.GeoDataFrame(frame, geometry=geometry, crs="EPSG:4326")
    raise ValueError(f"Unsupported source file type: {path.suffix}")


# Parse operator arguments for one source refresh cycle.
def parse_args() -> argparse.Namespace:
    """Parse operator arguments for one source refresh cycle."""
    parser = argparse.ArgumentParser(description="Run a source refresh cycle into the Supabase-first structure workflow.")
    parser.add_argument("--source-file", required=True, help="Prepared source file with canonical structure columns.")
    parser.add_argument("--source-name", default="nyc_pluto", help="Source name, such as nyc_pluto or overture.")
    parser.add_argument("--source-family", default="assessor", help="Source family used for provenance.")
    parser.add_argument("--source-as-of", default="latest", help="Upstream source vintage.")
    parser.add_argument("--refresh-cadence", default="quarterly", help="Refresh cadence label.")
    parser.add_argument("--data-refresh-timestamp", help="Explicit ISO datetime stamp for this data refresh.")
    parser.add_argument("--city", default="Manhattan", help="Refresh city.")
    parser.add_argument("--state", default="New York", help="Refresh state.")
    parser.add_argument("--store", choices=["in_memory", "supabase"], default="in_memory", help="Refresh persistence store.")
    parser.add_argument("--supabase-url", help="Supabase project URL for --store supabase.")
    parser.add_argument("--supabase-service-role-env", default="SUPABASE_SERVICE_ROLE_KEY", help="Env var containing Supabase service role key.")
    parser.add_argument("--dry-run", action="store_true", help="Compute staging/deltas without mutating the store.")
    parser.add_argument("--no-promote", action="store_true", help="Run QA but do not promote into canonical structures.")
    return parser.parse_args()


# Run the operator command and print a compact JSON summary.
def main() -> None:
    """Run the operator command and print a compact JSON summary."""
    args = parse_args()
    source_frame = load_source_frame(Path(args.source_file))
    config = PipelineConfig(
        refresh_city=args.city,
        refresh_state=args.state,
        refresh_source_name=args.source_name,
        refresh_source_family=args.source_family,
        refresh_source_as_of=args.source_as_of,
        refresh_cadence=args.refresh_cadence,
        data_refresh_timestamp=args.data_refresh_timestamp,
        supabase_url=args.supabase_url,
        supabase_service_role_env=args.supabase_service_role_env,
        dry_run=args.dry_run,
        promote_to_canonical=not args.no_promote,
    )
    store = build_refresh_store(config, args.store)
    result = run_refresh_cycle(
        args.source_name,
        args.city,
        args.state,
        config,
        source_frame=source_frame,
        store=store,
    )
    summary = {
        "source_run_id": result["source_run"]["source_run_id"],
        "status": result["source_run"]["status"],
        "data_refresh_timestamp": result["source_run"]["data_refresh_timestamp"],
        "raw_rows": len(result["raw_rows"]),
        "change_counts": result["source_run"]["metadata"].get("change_counts", {}),
        "promoted_count": result["promotion"]["promoted_count"],
        "failed_count": result["promotion"]["failed_count"],
        "release_gate_status": result["release_manifest"]["quality_contract"]["release_gates"]["status"],
        "release_gate_blockers": result["release_manifest"]["quality_contract"]["release_gates"]["blockers"],
        "dry_run": args.dry_run,
        "store": args.store,
    }
    print(json.dumps(json_safe(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
