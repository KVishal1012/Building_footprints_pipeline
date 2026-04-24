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

from pipeline_runtime import (  # noqa: E402
    configure_logging,
    config_section,
    dataclass_config_kwargs,
    load_json_object,
    logging_level,
    parse_places,
)


LOGGER = logging.getLogger("india_pipeline")


def load_india_structure_module():
    module_path = INDIA_DIR / "structure_pipeline.py"
    spec = importlib.util.spec_from_file_location("india_structure_pipeline", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the India structure pipeline from JSON config.")
    parser.add_argument(
        "--config",
        default=INDIA_DIR / "pipeline_config.example.json",
        type=Path,
        help="JSON run config with places, config, and logging sections.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate config without running the pipeline.")
    args = parser.parse_args()

    module = load_india_structure_module()
    payload = load_json_object(args.config)
    configure_logging(logging_level(payload))
    places = parse_places(payload.get("places"))
    config_kwargs = dataclass_config_kwargs(
        config_section(payload),
        module.PipelineConfig,
        repo_root=REPO_ROOT,
    )
    config = module.PipelineConfig(**config_kwargs)

    if args.dry_run:
        LOGGER.info("Validated India structure pipeline config for %d place(s)", len(places))
        return

    LOGGER.info("Starting India structure pipeline for %d place(s)", len(places))
    module.build_many_cities(places, config)
    LOGGER.info("India structure pipeline completed")


if __name__ == "__main__":
    main()
