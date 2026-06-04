from __future__ import annotations

import argparse
import logging

from structures_pipeline.config import PipelineConfig
from structures_pipeline.pipeline import parse_place_arg, run_pipeline


# Parse one place-keyed parcel source CLI argument into config form.
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
# Convert SQL footprint CLI arguments into an optional source dictionary.
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
        "units_column": args.sql_units_column,
        "height_column": args.sql_height_column,
        "stories_column": args.sql_stories_column,
        "occupant_count_column": args.sql_occupant_count_column,
        "where": args.sql_where,
        "crs": args.sql_crs,
        "source_name": args.sql_source_name,
        "sqlserver_geometry_methods": args.sqlserver_geometry_methods,
    }


# Convert SQL baseline CLI arguments into an optional baseline dictionary.
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


# Convert SQL Server export CLI arguments into an optional export dictionary.
def parse_sql_export_args(args: argparse.Namespace) -> dict | None:
    """Convert SQL Server export CLI arguments into an optional export dictionary."""
    if not args.export_sqlserver_table:
        return None
    return {
        "connection_env": args.export_sqlserver_connection_env,
        "table": args.export_sqlserver_table,
        "if_exists": args.export_sqlserver_if_exists,
        "geometry_column": args.export_sqlserver_geometry_column,
        "chunksize": args.export_sqlserver_chunksize,
        "fast_executemany": not args.no_export_fast_executemany,
    }


# Build the command-line parser for production and debug pipeline runs.
def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for production and debug pipeline runs."""
    parser = argparse.ArgumentParser(description="Build production US structure polygons.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--place", action="append", type=parse_place_arg, help="City and state as 'City, State'.")
    target.add_argument("--state", action="append", help="State abbreviation or name. Can be passed multiple times.")
    target.add_argument("--all-us-cities", action="store_true", help="Run all Census places in the 50 states plus DC.")
    parser.add_argument("--output-dir", default="data/output")
    parser.add_argument(
        "--no-local-outputs",
        action="store_true",
        help="Skip city parquet, master parquet, QA parquet, and manifest JSON outputs.",
    )
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
    parser.add_argument("--sql-connection-env", default="STRUCTURES_SQLSERVER_URL")
    parser.add_argument("--sql-table", help="SQL Server table/view to read structure geometries from.")
    parser.add_argument("--sql-query", help="SQL SELECT query to read structure geometries from.")
    parser.add_argument("--sql-geom-column", default="geom", help="Geometry column returned by the SQL source.")
    parser.add_argument("--sql-id-column", help="Stable ID column in the SQL source.")
    parser.add_argument("--sql-structure-type-column", help="Optional structure type/use column in the SQL source.")
    parser.add_argument("--sql-units-column", help="Optional unit-count column in the SQL source.")
    parser.add_argument("--sql-height-column", help="Optional height column in the SQL source.")
    parser.add_argument("--sql-stories-column", help="Optional stories column in the SQL source.")
    parser.add_argument("--sql-occupant-count-column", help="Optional authoritative occupant-count column in the SQL source.")
    parser.add_argument("--sql-where", help="Optional WHERE clause used with --sql-table.")
    parser.add_argument("--sql-crs", default="EPSG:4326", help="CRS for SQL geometries when the source does not provide one.")
    parser.add_argument("--sql-source-name", default="sql", help="Label recorded in FootprintSource for SQL rows.")
    parser.add_argument(
        "--sqlserver-geometry-methods",
        action="store_true",
        help="Read SQL Server geometry/geography via STAsBinary() and STSrid when using --sql-table.",
    )
    parser.add_argument("--baseline-sql-connection-env", default="STRUCTURES_SQLSERVER_URL")
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
    parser.add_argument(
        "--show-dataframe",
        action="store_true",
        help="Keep the final output in memory and print a pandas-style dataframe preview.",
    )
    parser.add_argument("--dataframe-preview-rows", type=int, default=10)
    parser.add_argument("--export-sqlserver-table", help="Final SQL Server output table as table or schema.table.")
    parser.add_argument("--export-sqlserver-connection-env", default="STRUCTURES_SQLSERVER_URL")
    parser.add_argument(
        "--export-sqlserver-if-exists",
        choices=["fail", "replace", "append"],
        default="fail",
        help="Behavior when the final SQL Server output table already exists.",
    )
    parser.add_argument("--export-sqlserver-geometry-column", default="geometry_wkt")
    parser.add_argument("--export-sqlserver-chunksize", type=int, default=1000)
    parser.add_argument("--no-export-fast-executemany", action="store_true")
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


# Parse CLI arguments, construct PipelineConfig, and run the selected targets.
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
    sql_export = parse_sql_export_args(args)
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
        sql_export=sql_export,
        return_dataframe=args.show_dataframe,
        dataframe_preview_rows=args.dataframe_preview_rows,
        write_local_outputs=not args.no_local_outputs,
        parcel_sources=dict(args.parcel_source),
    )
    result = run_pipeline(
        place_specs=args.place,
        state_filters=args.state,
        all_us_cities=args.all_us_cities,
        config=config,
    )
    if result.get("manifest_path"):
        logging.getLogger(__name__).info("Wrote manifest: %s", result["manifest_path"])
    else:
        logging.getLogger(__name__).info("Skipped local parquet/json outputs")
    if args.show_dataframe:
        dataframe = result.get("dataframe")
        if dataframe is not None:
            print(dataframe.head(args.dataframe_preview_rows).to_string(index=False))
    if result.get("sql_export"):
        logging.getLogger(__name__).info("Exported SQL Server table: %s", result["sql_export"])
