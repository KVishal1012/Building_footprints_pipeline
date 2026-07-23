from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import geopandas as gpd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_chennai_real_source import load_settings
from structures_pipeline.india import build_india_refresh_config
from structures_pipeline.india_osm import CHENNAI_CANONICAL_COLUMNS
from structures_pipeline.refresh import SupabaseRefreshStore, build_refresh_store, run_refresh_cycle
from structures_pipeline.utils import json_safe
from structures_pipeline.validation import validate_output


def source_sha256(path: Path) -> str:
    """Hash the acquired source so rerunning the same snapshot gets the same run ID."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_source_run_id(source_as_of: str, source_path: Path) -> str:
    """Build a stable source run ID from source, place, vintage, and content hash."""
    vintage = source_as_of.replace("-", "_")
    return (
        "openstreetmap_chennai_tamil_nadu_"
        f"{vintage}_{source_sha256(source_path)[:16]}"
    ).lower()


def validate_acceptance_inputs(canonical_path: Path, report_path: Path) -> tuple[gpd.GeoDataFrame, dict]:
    """Require a passed local acceptance receipt that matches the canonical snapshot."""
    if not canonical_path.is_file() or not report_path.is_file():
        raise FileNotFoundError(
            "Run scripts/run_chennai_real_source.py before the Supabase lifecycle."
        )
    canonical = gpd.read_parquet(canonical_path)
    report = json.loads(report_path.read_text())
    if report.get("status") != "passed":
        raise ValueError("Chennai real-source acceptance report did not pass")
    if report.get("quality", {}).get("release_gates", {}).get("status") != "passed":
        raise ValueError("Chennai canonical release gates did not pass")
    if int(report.get("source_counts", {}).get("canonical_count", -1)) != len(canonical):
        raise ValueError("Acceptance report row count does not match the canonical snapshot")
    if set(canonical["City"].astype(str)) != {"Chennai"}:
        raise ValueError("Canonical snapshot contains a city other than Chennai")
    if set(canonical["State"].astype(str)) != {"Tamil Nadu"}:
        raise ValueError("Canonical snapshot contains a state other than Tamil Nadu")
    if list(canonical.columns) != CHENNAI_CANONICAL_COLUMNS:
        raise ValueError("Canonical snapshot columns do not match the approved Chennai contract")
    validate_output(canonical)
    return canonical, report


def run(settings) -> dict:
    """Run Chennai staging, delta detection, QA, and optional atomic promotion."""
    canonical_path = Path(settings.CANONICAL_OUTPUT_PATH)
    report_path = Path(settings.ACCEPTANCE_REPORT_PATH)
    canonical, acceptance = validate_acceptance_inputs(canonical_path, report_path)
    source_as_of = str(acceptance["source_as_of"])
    run_id = deterministic_source_run_id(source_as_of, Path(settings.OSM_BUILDINGS_PATH))
    dry_run = bool(getattr(settings, "DRY_RUN", True))
    store_name = str(getattr(settings, "SUPABASE_STORE", "in_memory"))
    config = build_india_refresh_config(
        city_slug="chennai",
        source_name="openstreetmap",
        source_as_of=source_as_of,
        source_run_id=run_id,
        data_refresh_timestamp=acceptance["data_refresh_timestamp"],
        dry_run=dry_run,
        promote_to_canonical=bool(getattr(settings, "PROMOTE_TO_CANONICAL", True)),
        supabase_url=getattr(settings, "SUPABASE_URL", None),
        supabase_service_role_env=str(
            getattr(settings, "SUPABASE_SERVICE_ROLE_ENV", "SUPABASE_SERVICE_ROLE_KEY")
        ),
    )
    config.refresh_compact_results = True
    config.refresh_require_nonempty = True
    config.refresh_metadata.update(
        {
            "source_authority": "OpenStreetMap contributors",
            "provenance_tier": "open_community",
            "acceptance_report": str(report_path),
            "source_sha256": source_sha256(Path(settings.OSM_BUILDINGS_PATH)),
        }
    )
    store = build_refresh_store(config, store_name)
    preflight = {"status": "not_required", "tables": []}
    if isinstance(store, SupabaseRefreshStore):
        preflight = store.preflight()
    result = run_refresh_cycle(
        "openstreetmap",
        "Chennai",
        "Tamil Nadu",
        config,
        source_frame=canonical,
        store=store,
    )
    lifecycle = {
        "status": "passed"
        if result["release_manifest"]["quality_contract"]["release_gates"]["status"] == "passed"
        and result["promotion"]["failed_count"] == 0
        else "failed",
        "dry_run": dry_run,
        "store": store_name,
        "source_run_id": run_id,
        "source_sha256": config.refresh_metadata["source_sha256"],
        "source_as_of": source_as_of,
        "data_refresh_timestamp": result["source_run"]["data_refresh_timestamp"],
        "input_rows": result["source_run"]["row_count"],
        "change_counts": result["source_run"]["metadata"]["change_counts"],
        "promoted_count": result["promotion"]["promoted_count"],
        "failed_count": result["promotion"]["failed_count"],
        "release_gate_status": result["release_manifest"]["quality_contract"]["release_gates"]["status"],
        "release_gate_blockers": result["release_manifest"]["quality_contract"]["release_gates"]["blockers"],
        "preflight": preflight,
    }
    lifecycle_path = Path(settings.LIFECYCLE_REPORT_PATH)
    lifecycle_path.parent.mkdir(parents=True, exist_ok=True)
    lifecycle_path.write_text(json.dumps(json_safe(lifecycle), indent=2, sort_keys=True))
    lifecycle["lifecycle_report"] = str(lifecycle_path)
    return lifecycle


def parse_args() -> argparse.Namespace:
    """Parse only the local settings module path; credentials remain environment based."""
    parser = argparse.ArgumentParser(description="Run the Chennai Supabase refresh lifecycle.")
    parser.add_argument("--settings", default="india_local_inputs.py")
    return parser.parse_args()


def main() -> None:
    """Run the lifecycle and print its compact receipt."""
    args = parse_args()
    print(json.dumps(json_safe(run(load_settings(Path(args.settings)))), indent=2))


if __name__ == "__main__":
    main()
