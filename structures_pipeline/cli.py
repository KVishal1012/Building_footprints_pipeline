from __future__ import annotations

import argparse
import logging

from structures_pipeline.config import PipelineConfig
from structures_pipeline.pipeline import parse_place_arg, run_pipeline


def parse_parcel_source_arg(value: str) -> tuple[str, dict]:
    """Parse one place-keyed parcel source CLI argument into config form."""
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "Use place_geoid_or_slug=path_or_url, for example 1714000=data/parcels.gpkg"
        )
    key, source_value = value.split("=", 1)
    source_value = source_value.strip()
    source = {"url": source_value} if source_value.lower().startswith("http") else {"path": source_value}
    return key.strip(), source
def parse_sql_source_args(args: argparse.Namespace) -> dict | None:
    """Convert SQL footprint CLI arguments into an optional source dictionary."""
    if not args.sql_table and not args.sql_query:
        return None
    if args.sql_table and args.sql_query:
        raise argparse.ArgumentTypeError("Use either --sql-table or --sql-query, not both.")
    return {
        "connection_env": args.sql_connection_env,
        "table": args.sql_table,
        "query": args.sql_query,
        "geom_column": args.sql_geom_column,
        "id_column": args.sql_id_column,
        "structure_type_column": args.sql_structure_type_column,
        "height_column": args.sql_height_column,
        "stories_column": args.sql_stories_column,
        "where": args.sql_where,
        "crs": args.sql_crs,
        "source_name": args.sql_source_name,
    }


def parse_sql_baseline_args(args: argparse.Namespace) -> dict | None:
    """Convert SQL baseline CLI arguments into an optional baseline dictionary."""
    if not args.baseline_sql_table and not args.baseline_sql_query:
        return None
    if args.baseline_sql_table and args.baseline_sql_query:
        raise argparse.ArgumentTypeError(
            "Use either --baseline-sql-table or --baseline-sql-query, not both."
        )
    return {
        "connection_env": args.baseline_sql_connection_env,
        "table": args.baseline_sql_table,
        "query": args.baseline_sql_query,
        "geom_column": args.baseline_sql_geom_column,
        "id_column": args.baseline_sql_id_column,
        "where": args.baseline_sql_where,
        "crs": args.baseline_sql_crs,
        "buffer_meters": args.baseline_buffer_meters,
        "sqlserver_geometry_methods": args.baseline_sqlserver_geometry_methods,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for production and debug pipeline runs."""
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
    parser.add_argument("--no-sql", action="store_true")
    parser.add_argument("--sql-connection-env", default="STRUCTURES_SQL_URL")
    parser.add_argument("--sql-table", help="SQL table/view to read structure geometries from.")
    parser.add_argument("--sql-query", help="SQL SELECT query to read structure geometries from.")
    parser.add_argument("--sql-geom-column", default="geom", help="Geometry column returned by the SQL source.")
    parser.add_argument("--sql-id-column", help="Stable ID column in the SQL source.")
    parser.add_argument("--sql-structure-type-column", help="Optional structure type/use column in the SQL source.")
    parser.add_argument("--sql-height-column", help="Optional height column in the SQL source.")
    parser.add_argument("--sql-stories-column", help="Optional stories column in the SQL source.")
    parser.add_argument("--sql-where", help="Optional WHERE clause used with --sql-table.")
    parser.add_argument("--sql-crs", default="EPSG:4326", help="CRS for SQL geometries when the source does not provide one.")
    parser.add_argument("--sql-source-name", default="sql", help="Label recorded in FootprintSource for SQL rows.")
    parser.add_argument("--baseline-sql-connection-env", default="STRUCTURES_SQL_URL")
    parser.add_argument("--baseline-sql-table", help="SQL Server baseline table/view used to build a buffered AOI.")
    parser.add_argument("--baseline-sql-query", help="SQL SELECT query that returns baseline geometries.")
    parser.add_argument("--baseline-sql-geom-column", default="geom", help="Baseline geometry column.")
    parser.add_argument("--baseline-sql-id-column", help="Stable baseline ID column added to output structures.")
    parser.add_argument("--baseline-sql-where", help="Optional WHERE clause used with --baseline-sql-table.")
    parser.add_argument("--baseline-sql-crs", default="EPSG:4326")
    parser.add_argument("--baseline-buffer-meters", type=float, default=100.0)
    parser.add_argument(
        "--baseline-sqlserver-geometry-methods",
        action="store_true",
        help="Read SQL Server geometry/geography via STAsBinary() and STSrid when using --baseline-sql-table.",
    )
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
    """Parse CLI arguments, construct PipelineConfig, and run the selected targets."""
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sql_source = parse_sql_source_args(args)
    sql_baseline_source = parse_sql_baseline_args(args)
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
        use_sql=not args.no_sql,
        use_osm=args.use_osm,
        use_nsi=not args.no_nsi,
        use_census=not args.no_census,
        use_parcels=not args.no_parcels,
        sql_footprint_source=sql_source,
        sql_baseline_source=sql_baseline_source,
        parcel_sources=dict(args.parcel_source),
    )
    result = run_pipeline(
        place_specs=args.place,
        state_filters=args.state,
        all_us_cities=args.all_us_cities,
        config=config,
    )
    logging.getLogger(__name__).info("Wrote manifest: %s", result["manifest_path"])
