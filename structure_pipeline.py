from __future__ import annotations

from structures_pipeline import (
    PipelineConfig,
    SqlServerPipelineSettings,
    build_sql_server_pipeline_config,
    build_city_structures,
    build_many_cities,
    build_places,
    run_pipeline,
    run_sql_server_pipeline,
)
from structures_pipeline.cli import main
from structures_pipeline.pipeline import parse_place_arg as parse_place

__all__ = [
    "PipelineConfig",
    "SqlServerPipelineSettings",
    "build_sql_server_pipeline_config",
    "build_city_structures",
    "build_many_cities",
    "build_places",
    "run_pipeline",
    "run_sql_server_pipeline",
    "parse_place",
    "main",
]


if __name__ == "__main__":
    main()
