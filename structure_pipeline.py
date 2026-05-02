from __future__ import annotations

from structures_pipeline import (
    PipelineConfig,
    build_city_structures,
    build_many_cities,
    build_places,
    run_pipeline,
)
from structures_pipeline.cli import main
from structures_pipeline.pipeline import parse_place_arg as parse_place

__all__ = [
    "PipelineConfig",
    "build_city_structures",
    "build_many_cities",
    "build_places",
    "run_pipeline",
    "parse_place",
    "main",
]


if __name__ == "__main__":
    main()
