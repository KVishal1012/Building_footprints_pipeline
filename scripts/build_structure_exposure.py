from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from structures_pipeline.exposure import (
    build_ward_structure_exposure,
    load_structure_frame,
    load_ward_frame,
    write_ward_structure_exposure,
)
from structures_pipeline.utils import json_safe


def parse_args() -> argparse.Namespace:
    """Parse operator arguments for building a structure exposure artifact."""
    parser = argparse.ArgumentParser(description="Build ward-level structure exposure features.")
    parser.add_argument("--structures", required=True, type=Path, help="Canonical structure input file.")
    parser.add_argument("--wards", required=True, type=Path, help="Ward polygon file.")
    parser.add_argument("--ward-id-column", default="ward_no", help="Ward id column in the ward polygon file.")
    parser.add_argument("--output", required=True, type=Path, help="Output JSON artifact path.")
    parser.add_argument("--expected-ward-count", type=int, help="Fail unless this ward count is present.")
    parser.add_argument("--allow-unassigned", action="store_true", help="Allow structures outside all ward polygons.")
    return parser.parse_args()


def main() -> None:
    """Build and write ward-level structure exposure features."""
    args = parse_args()
    structures = load_structure_frame(args.structures)
    wards = load_ward_frame(args.wards, ward_id_column=args.ward_id_column)
    payload = build_ward_structure_exposure(
        structures,
        wards,
        strict=not args.allow_unassigned,
        expected_ward_count=args.expected_ward_count,
    )
    write_ward_structure_exposure(payload, args.output)
    summary = {
        "output": str(args.output),
        "ward_count": len(payload["wards"]),
        "structure_count": payload["metadata"]["assignment"]["structure_count"],
        "assigned_count": payload["metadata"]["assignment"]["assigned_count"],
        "unassigned_count": payload["metadata"]["assignment"]["unassigned_count"],
        "ambiguous_count": payload["metadata"]["assignment"]["ambiguous_count"],
        "release_gate_status": payload["metadata"]["release_gate_status"],
        "release_gate_blockers": payload["metadata"]["release_gate_blockers"],
    }
    print(json.dumps(json_safe(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
