from __future__ import annotations

import argparse
import logging

from structures_pipeline.config import PipelineConfig
from structures_pipeline.pipeline import parse_place_arg, run_pipeline


def parse_parcel_source_arg(value: str) -> tuple[str, dict]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "Use place_geoid_or_slug=path_or_url, for example 1714000=data/parcels.gpkg"
        )
    key, source_value = value.split("=", 1)
    source_value = source_value.strip()
    source = {"url": source_value} if source_value.lower().startswith("http") else {"path": source_value}
    return key.strip(), source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build production US structure polygons.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--place", action="append", type=parse_place_arg, help="City and state as 'City, State'.")
    target.add_argument("--state", action="append", help="State abbreviation or name. Can be passed multiple times.")
    target.add_argument("--all-us-cities", action="store_true", help="Run all Census places in the 50 states plus DC.")
    parser.add_argument("--output-dir", default="data/output")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--source-version", default="latest")
    parser.add_argument("--census-year", type=int, default=2025)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--overwrite-raw", action="store_true")
    parser.add_argument("--no-overture", action="store_true")
    parser.add_argument("--no-microsoft", action="store_true")
    parser.add_argument("--use-osm", action="store_true")
    parser.add_argument("--no-nsi", action="store_true")
    parser.add_argument("--no-census", action="store_true")
    parser.add_argument("--no-parcels", action="store_true")
    parser.add_argument(
        "--parcel-source",
        action="append",
        type=parse_parcel_source_arg,
        default=[],
        help="Parcel source as place_geoid_or_slug=path_or_url.",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = PipelineConfig(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        raw_dir=args.raw_dir,
        cache_dir=args.cache_dir,
        source_version=args.source_version,
        census_year=args.census_year,
        download_missing=not args.no_download,
        overwrite_raw=args.overwrite_raw,
        use_overture=not args.no_overture,
        use_microsoft=not args.no_microsoft,
        use_osm=args.use_osm,
        use_nsi=not args.no_nsi,
        use_census=not args.no_census,
        use_parcels=not args.no_parcels,
        parcel_sources=dict(args.parcel_source),
    )
    result = run_pipeline(
        place_specs=args.place,
        state_filters=args.state,
        all_us_cities=args.all_us_cities,
        config=config,
    )
    logging.getLogger(__name__).info("Wrote manifest: %s", result["manifest_path"])
