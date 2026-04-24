from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
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
from structure_pipeline import PipelineConfig, build_many_cities  # noqa: E402


LOGGER = logging.getLogger("root_pipeline")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the root structure pipeline from JSON config.")
    parser.add_argument(
        "--config",
        default=REPO_ROOT / "configs/root_pipeline.example.json",
        type=Path,
        help="JSON run config with places, config, and logging sections.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate config without running the pipeline.")
    args = parser.parse_args()

    payload = load_json_object(args.config)
    configure_logging(logging_level(payload))
    places = parse_places(payload.get("places"))
    config_kwargs = dataclass_config_kwargs(
        config_section(payload),
        PipelineConfig,
        repo_root=REPO_ROOT,
    )
    config = PipelineConfig(**config_kwargs)

    if args.dry_run:
        LOGGER.info("Validated root structure pipeline config for %d place(s)", len(places))
        return

    LOGGER.info("Starting root structure pipeline for %d place(s)", len(places))
    build_many_cities(places, config)
    LOGGER.info("Root structure pipeline completed")


if __name__ == "__main__":
    main()
