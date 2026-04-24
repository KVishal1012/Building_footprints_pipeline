from __future__ import annotations

import argparse
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
    config_section,
    dataclass_config_kwargs,
    load_json_object,
    logging_level,
    source_config_path,
)
from processing_pipeline import (  # noqa: E402
    ProcessingConfig,
    read_source_config,
    run_processing_pipeline,
)


LOGGER = logging.getLogger("india_processing")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the India processing pipeline from JSON config.")
    parser.add_argument(
        "--config",
        default=INDIA_DIR / "processing_pipeline_config.example.json",
        type=Path,
        help="JSON run config with source_config, config, and logging sections.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate config without running the pipeline.")
    args = parser.parse_args()

    payload = load_json_object(args.config)
    configure_logging(logging_level(payload))
    source_path = source_config_path(payload, REPO_ROOT)
    config_kwargs = dataclass_config_kwargs(
        config_section(payload),
        ProcessingConfig,
        repo_root=REPO_ROOT,
    )
    config = ProcessingConfig(**config_kwargs)

    if args.dry_run:
        LOGGER.info("Validated India processing pipeline config with source config %s", source_path)
        return

    LOGGER.info("Starting India processing pipeline with source config %s", source_path)
    run_processing_pipeline(read_source_config(source_path), config)
    LOGGER.info("India processing pipeline completed")


if __name__ == "__main__":
    main()
