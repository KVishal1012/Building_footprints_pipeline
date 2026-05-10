from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INDIA_DIR = REPO_ROOT / "India"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(INDIA_DIR) not in sys.path:
    sys.path.insert(0, str(INDIA_DIR))

from pipeline_runtime import (  # noqa: E402
    configure_logging,
    dataclass_config_kwargs,
    load_json_object,
    logging_level,
    parse_places,
    resolve_config_path,
)
from processing_pipeline import (  # noqa: E402
    ProcessingConfig,
    read_source_config,
    run_processing_pipeline,
)
from production_verification import (  # noqa: E402
    VerificationConfig,
    verify_outputs,
)


LOGGER = logging.getLogger("india_realworld_sequence")


def load_india_structure_module():
    module_path = INDIA_DIR / "structure_pipeline.py"
    spec = importlib.util.spec_from_file_location("india_structure_pipeline", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _dict(value, key: str) -> dict:
    out = value.get(key, {})
    if out is None:
        return {}
    if not isinstance(out, dict):
        raise ValueError(f"{key!r} must be a JSON object when provided")
    return dict(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run India pipeline sequence: OSM-first structures, full-source structures, and scenario processing."
    )
    parser.add_argument(
        "--config",
        default=INDIA_DIR / "realworld_sequence_config.example.json",
        type=Path,
        help="JSON sequence config.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate config without executing pipeline steps.")
    parser.add_argument("--skip-osm-first", action="store_true", help="Skip OSM-first structure run.")
    parser.add_argument("--skip-full-sources", action="store_true", help="Skip full-source structure run.")
    parser.add_argument("--skip-scenarios", action="store_true", help="Skip scenario processing run.")
    parser.add_argument(
        "--verification-config",
        default=None,
        type=Path,
        help="Optional JSON verification config to run after scenario processing.",
    )
    args = parser.parse_args()

    payload = load_json_object(args.config)
    configure_logging(logging_level(payload))
    places = parse_places(payload.get("places"))

    structure_module = load_india_structure_module()
    structure_config_raw = _dict(payload, "structure_config")
    osm_first_overrides = _dict(payload, "osm_first_overrides")
    full_source_overrides = _dict(payload, "full_source_overrides")
    processing_config_raw = _dict(payload, "processing_config")
    scenario_source_config_value = payload.get(
        "scenario_source_config", "India/scenario_sources.example.json"
    )
    scenario_source_config_path = resolve_config_path(
        scenario_source_config_value, REPO_ROOT
    )
    verification_config_path = (
        resolve_config_path(args.verification_config, REPO_ROOT)
        if args.verification_config is not None
        else None
    )

    structure_base_kwargs = dataclass_config_kwargs(
        structure_config_raw,
        structure_module.PipelineConfig,
        repo_root=REPO_ROOT,
    )
    osm_first_defaults = {
        "download_missing": True,
        "use_overture": False,
        "use_microsoft": False,
        "use_osm": True,
        "use_nsi": False,
        "use_census": False,
        "use_parcels": False,
        "add_osm_unmatched": True,
        "strict_sources": False,
    }
    full_source_defaults = {
        "download_missing": True,
        "use_overture": True,
        "use_microsoft": True,
        "use_osm": True,
        "use_nsi": False,
        "use_census": False,
        "use_parcels": True,
        "add_microsoft_unmatched": True,
        "add_osm_unmatched": True,
        "strict_sources": False,
    }
    osm_first_config = structure_module.PipelineConfig(
        **(structure_base_kwargs | osm_first_defaults | osm_first_overrides)
    )
    full_source_config = structure_module.PipelineConfig(
        **(structure_base_kwargs | full_source_defaults | full_source_overrides)
    )
    processing_kwargs = dataclass_config_kwargs(
        processing_config_raw,
        ProcessingConfig,
        repo_root=REPO_ROOT,
    )
    processing_config = ProcessingConfig(**processing_kwargs)

    if args.dry_run:
        LOGGER.info("Validated sequence config for %d place(s)", len(places))
        LOGGER.info("Scenario source config path: %s", scenario_source_config_path)
        if verification_config_path is not None:
            VerificationConfig.from_json(verification_config_path)
            LOGGER.info("Verification config path: %s", verification_config_path)
        return

    if not args.skip_osm_first:
        LOGGER.info("Step 1/3: running OSM-first structure pipeline")
        structure_module.build_many_cities(places, osm_first_config)
    if not args.skip_full_sources:
        LOGGER.info("Step 2/3: running full-source structure pipeline")
        structure_module.build_many_cities(places, full_source_config)
    if not args.skip_scenarios:
        LOGGER.info("Step 3/3: running scenario processing pipeline")
        sources = read_source_config(scenario_source_config_path)
        run_processing_pipeline(sources, processing_config)
    if verification_config_path is not None:
        LOGGER.info("Running production verification with %s", verification_config_path)
        report = verify_outputs(VerificationConfig.from_json(verification_config_path))
        if not report["passed"]:
            raise RuntimeError(
                "Production verification failed: "
                + "; ".join(report["errors"])
            )

    LOGGER.info("India real-world sequence completed")


if __name__ == "__main__":
    main()
