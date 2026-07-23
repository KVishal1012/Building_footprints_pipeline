from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from structures_pipeline.exposure import build_ward_structure_exposure, write_ward_structure_exposure
from structures_pipeline.india_osm import build_chennai_osm_structures
from structures_pipeline.utils import json_safe


def load_settings(path: Path) -> ModuleType:
    """Load machine-local source paths without placing them in CLI history."""
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing settings module: {path}. Copy india_local_inputs.example.py "
            "to india_local_inputs.py and set the local paths."
        )
    spec = importlib.util.spec_from_file_location("india_local_inputs", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import settings module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(settings: ModuleType) -> dict:
    """Build canonical structures, ward exposure, and a local acceptance receipt."""
    canonical, wards, report = build_chennai_osm_structures(
        buildings_path=Path(settings.OSM_BUILDINGS_PATH),
        wards_path=Path(settings.GCC_WARDS_PATH),
        manifest_path=Path(settings.SOURCE_MANIFEST_PATH),
        data_refresh_timestamp=getattr(settings, "DATA_REFRESH_TIMESTAMP", None),
    )
    exposure = build_ward_structure_exposure(
        canonical,
        wards,
        strict=True,
        expected_ward_count=200,
        ward_id_column="ward_id",
        allow_ward_overlaps=True,
        resolve_ambiguous_by_largest_overlap=True,
    )
    canonical_path = Path(settings.CANONICAL_OUTPUT_PATH)
    exposure_path = Path(settings.EXPOSURE_OUTPUT_PATH)
    report_path = Path(settings.ACCEPTANCE_REPORT_PATH)
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    canonical.to_parquet(canonical_path, index=False)
    write_ward_structure_exposure(exposure, exposure_path)
    report = {
        **report,
        "canonical_output": str(canonical_path),
        "exposure_output": str(exposure_path),
        "exposure_release_gate_status": exposure["metadata"]["release_gate_status"],
        "exposure_ward_count": len(exposure["wards"]),
        "approved_output_columns": list(canonical.columns),
    }
    report_path.write_text(json.dumps(json_safe(report), indent=2, sort_keys=True))
    return {
        "status": report["status"],
        "canonical_rows": len(canonical),
        "canonical_output": str(canonical_path),
        "exposure_output": str(exposure_path),
        "acceptance_report": str(report_path),
        "release_gate_status": report["quality"]["release_gates"]["status"],
        "exposure_release_gate_status": report["exposure_release_gate_status"],
    }


def parse_args() -> argparse.Namespace:
    """Parse only the local settings module path; data inputs stay in that module."""
    parser = argparse.ArgumentParser(description="Build the Chennai real-source canonical snapshot.")
    parser.add_argument("--settings", default="india_local_inputs.py")
    return parser.parse_args()


def main() -> None:
    """Run Chennai acceptance and print a compact machine-readable receipt."""
    args = parse_args()
    print(json.dumps(json_safe(run(load_settings(Path(args.settings)))), indent=2))


if __name__ == "__main__":
    main()
