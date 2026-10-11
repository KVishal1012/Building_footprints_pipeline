"""Build one reviewed-source Toronto pilot package locally."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from structures_pipeline.toronto import build_toronto_pack


def main() -> None:
    """Parse explicit file inputs and print the resulting release manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery-mode", choices=["buildings", "components"], default="buildings")
    parser.add_argument("--citywide-dir", type=Path)
    parser.add_argument("--source-file", type=Path)
    for name in ("source-manifest", "study-area", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        if args.delivery_mode == "components":
            if args.citywide_dir is None or args.source_file is not None:
                raise ValueError("Component mode requires --citywide-dir and no --source-file.")
            from scripts.build_toronto_demo import build_demo
            release = build_demo(args.citywide_dir, args.study_area, args.output_dir,
                                 delivery_mode="components", qualification_file=args.source_manifest)
        else:
            if args.source_file is None or args.citywide_dir is not None:
                raise ValueError("Building mode requires --source-file and no --citywide-dir.")
            release = build_toronto_pack(args.source_file, args.source_manifest, args.study_area, args.output_dir)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Toronto pilot blocked: {exc}\n")
    print(json.dumps(release, indent=2))


if __name__ == "__main__":
    main()
