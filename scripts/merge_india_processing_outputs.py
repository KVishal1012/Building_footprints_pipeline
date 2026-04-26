from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd


def read_layers(output_dir: Path) -> gpd.GeoDataFrame:
    path = output_dir / "processing_layers.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing processing layers: {path}")
    return gpd.read_parquet(path)


def read_links(output_dir: Path) -> pd.DataFrame:
    path = output_dir / "structure_processing_links.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing processing links: {path}")
    return pd.read_parquet(path)


def merge_outputs(input_dirs: list[Path], output_dir: Path) -> tuple[Path, Path, Path]:
    layers = [read_layers(path) for path in input_dirs]
    links = [read_links(path) for path in input_dirs]
    merged_layers = gpd.GeoDataFrame(
        pd.concat(layers, ignore_index=True),
        geometry="geometry",
        crs=layers[0].crs if layers else "EPSG:4326",
    )
    merged_links = pd.concat(links, ignore_index=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    layer_path = output_dir / "processing_layers.parquet"
    link_path = output_dir / "structure_processing_links.parquet"
    metrics_path = output_dir / "processing_metrics.json"

    merged_layers.to_parquet(layer_path, index=False)
    merged_links.to_parquet(link_path, index=False)
    unique_linked = int(merged_links["StructureID"].nunique()) if not merged_links.empty else 0
    metrics = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dirs": [str(path) for path in input_dirs],
        "total_layer_rows": int(len(merged_layers)),
        "total_links": int(len(merged_links)),
        "unique_linked_structures": unique_linked,
        "rows_by_city": merged_layers["City"].value_counts(dropna=False).to_dict(),
        "rows_by_scenario": merged_layers["Scenario"].value_counts(dropna=False).to_dict(),
        "rows_by_source_name": merged_layers["SourceName"].value_counts(dropna=False).to_dict(),
    }
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n")
    return layer_path, link_path, metrics_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge per-city India processing outputs for dashboard use."
    )
    parser.add_argument(
        "--input-dir",
        action="append",
        required=True,
        type=Path,
        help="Directory containing processing_layers.parquet and structure_processing_links.parquet. Pass once per city.",
    )
    parser.add_argument(
        "--output-dir",
        default=Path("India/data/processing/output"),
        type=Path,
        help="Directory for merged dashboard outputs.",
    )
    args = parser.parse_args()

    layer_path, link_path, metrics_path = merge_outputs(args.input_dir, args.output_dir)
    print(f"Merged layers: {layer_path}")
    print(f"Merged links: {link_path}")
    print(f"Merged metrics: {metrics_path}")


if __name__ == "__main__":
    main()
