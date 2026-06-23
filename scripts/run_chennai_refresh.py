from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_refresh_pipeline import load_source_frame
from structures_pipeline.india import (
    INDIA_SOURCE_REGISTRY,
    build_india_refresh_config,
    default_source_path,
    get_india_source,
    get_tamil_nadu_city,
    india_source_registry_rows,
    tamil_nadu_city_registry_rows,
)
from structures_pipeline.refresh import build_refresh_store, run_refresh_cycle
from structures_pipeline.utils import json_safe


def parse_args() -> argparse.Namespace:
    """Parse operator arguments for the Chennai refresh runner."""
    parser = argparse.ArgumentParser(description="Run the Chennai real-source refresh workflow.")
    parser.add_argument("--source-file", default=str(default_source_path("chennai")), help="Prepared Chennai source file.")
    parser.add_argument(
        "--source-name",
        default="chennai_overture_osm_fallback",
        choices=sorted(INDIA_SOURCE_REGISTRY),
        help="Registered India source to apply to this refresh.",
    )
    parser.add_argument("--source-as-of", help="Override source vintage for this refresh.")
    parser.add_argument("--data-refresh-timestamp", help="Explicit ISO datetime stamp for this refresh.")
    parser.add_argument("--store", choices=["in_memory", "supabase"], default="in_memory", help="Persistence store.")
    parser.add_argument("--supabase-url", help="Supabase project URL for --store supabase.")
    parser.add_argument(
        "--supabase-service-role-env",
        default="SUPABASE_SERVICE_ROLE_KEY",
        help="Environment variable containing the Supabase service role key.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute staging, deltas, and QA without mutating the store.")
    parser.add_argument("--no-promote", action="store_true", help="Run QA but do not promote rows into canonical structures.")
    parser.add_argument(
        "--include-registries",
        action="store_true",
        help="Include Tamil Nadu city and India source registry rows in the JSON summary.",
    )
    return parser.parse_args()


def build_summary(result: dict, *, source_name: str, include_registries: bool) -> dict:
    """Build the compact JSON summary printed by the Chennai refresh runner."""
    city = get_tamil_nadu_city("chennai")
    source = get_india_source(source_name)
    manifest = result["release_manifest"]
    release_gates = manifest["quality_contract"]["release_gates"]
    summary = {
        "city": city.city,
        "state": city.state,
        "country": city.country,
        "coverage_tier": city.coverage_tier,
        "source_name": source.source_name,
        "source_family": source.source_family,
        "source_treatment": source.treatment,
        "source_run_id": result["source_run"]["source_run_id"],
        "refresh_status": result["source_run"]["status"],
        "data_refresh_timestamp": result["source_run"]["data_refresh_timestamp"],
        "raw_rows": len(result["raw_rows"]),
        "change_counts": result["source_run"]["metadata"].get("change_counts", {}),
        "promoted_count": result["promotion"]["promoted_count"],
        "failed_count": result["promotion"]["failed_count"],
        "release_gate_status": release_gates["status"],
        "release_gate_blockers": release_gates["blockers"],
        "tamil_nadu_expansion_targets": [
            row["city"] for row in tamil_nadu_city_registry_rows() if row["status"] == "planned_expansion"
        ],
    }
    if include_registries:
        summary["tamil_nadu_city_registry"] = tamil_nadu_city_registry_rows()
        summary["india_source_registry"] = india_source_registry_rows()
    return json_safe(summary)


def run_chennai_refresh(args: argparse.Namespace) -> dict:
    """Run Chennai staging, change detection, QA promotion, and release metadata."""
    source_frame = load_source_frame(Path(args.source_file))
    config = build_india_refresh_config(
        city_slug="chennai",
        source_name=args.source_name,
        source_as_of=args.source_as_of,
        data_refresh_timestamp=args.data_refresh_timestamp,
        dry_run=args.dry_run,
        promote_to_canonical=not args.no_promote,
        supabase_url=args.supabase_url,
        supabase_service_role_env=args.supabase_service_role_env,
    )
    store = build_refresh_store(config, args.store)
    return run_refresh_cycle(
        args.source_name,
        config.refresh_city or "Chennai",
        config.refresh_state or "Tamil Nadu",
        config,
        source_frame=source_frame,
        store=store,
    )


def main() -> None:
    """Run the Chennai refresh command and print a JSON summary."""
    args = parse_args()
    result = run_chennai_refresh(args)
    print(json.dumps(build_summary(result, source_name=args.source_name, include_registries=args.include_registries), indent=2))


if __name__ == "__main__":
    main()
