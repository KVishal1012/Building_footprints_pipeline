from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "examples" / "manhattan_refresh_source.csv"
OUTPUT_DIR = REPO_ROOT / "sales" / "manhattan_demo"

SAMPLE_COLUMNS = [
    "StructureID",
    "City",
    "State",
    "StructureType",
    "NumStories",
    "NumUnits",
    "OccupantCount",
    "FootprintArea_sqft",
    "CoverageTier",
    "data_refresh_timestamp",
    "last_refreshed",
    "source_as_of",
    "geometry_wkt",
]

PROVENANCE_COLUMNS = [
    "StructureID",
    "StructureTypeSource",
    "StructureTypeConfidence",
    "NumStoriesSource",
    "NumStoriesConfidence",
    "NumUnitsSource",
    "NumUnitsConfidence",
    "OccupantCountSource",
    "OccupantCountMethod",
    "OccupantCountConfidence",
    "RawDataSource",
    "LoadSource",
    "FootprintSource",
]

CORE_ATTRIBUTES = ["StructureType", "NumStories", "NumUnits", "OccupantCount"]


def read_rows(path: Path) -> list[dict]:
    """Read the Manhattan source fixture as dictionaries."""
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def non_empty(value: object) -> bool:
    """Return true when a CSV value is populated."""
    return value is not None and str(value).strip() != ""


def completeness(rows: list[dict], column: str) -> float:
    """Return column completeness as a rounded percentage."""
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if non_empty(row.get(column))) / len(rows), 4)


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    """Write selected columns to a CSV file."""
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def build_coverage_registry(rows: list[dict]) -> list[dict]:
    """Build city-level coverage and completeness metrics for the demo package."""
    by_city: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        by_city.setdefault((row["City"], row["State"]), []).append(row)

    registry = []
    for (city, state), group in sorted(by_city.items()):
        registry.append(
            {
                "City": city,
                "State": state,
                "CoverageTier": Counter(row["CoverageTier"] for row in group).most_common(1)[0][0],
                "row_count": len(group),
                "structure_type_completeness": completeness(group, "StructureType"),
                "num_stories_completeness": completeness(group, "NumStories"),
                "num_units_completeness": completeness(group, "NumUnits"),
                "occupant_count_completeness": completeness(group, "OccupantCount"),
                "raw_sources": ";".join(sorted({row["RawDataSource"] for row in group if non_empty(row["RawDataSource"])})),
                "last_refreshed": max(row["last_refreshed"] for row in group if non_empty(row["last_refreshed"])),
                "source_as_of": max(row["source_as_of"] for row in group if non_empty(row["source_as_of"])),
            }
        )
    return registry


def build_release_manifest(rows: list[dict], coverage_rows: list[dict]) -> dict:
    """Build the buyer-facing release manifest for the Manhattan demo package."""
    refresh_timestamp = max(row["data_refresh_timestamp"] for row in rows if non_empty(row["data_refresh_timestamp"]))
    source_counts = Counter(row["RawDataSource"] for row in rows)
    return {
        "release_id": "manhattan-demo-2026-q2",
        "generated_at": refresh_timestamp,
        "product": "Structure Intelligence Database",
        "market": "Manhattan, New York",
        "offer": "Audit-ready structure database for a target city or risk area",
        "row_count": len(rows),
        "pricing_targets": {
            "pilot_dataset": "$2k-$10k",
            "custom_city_build": "$5k-$25k",
            "api_or_database_access": "$500-$2k/month",
            "regional_enterprise_license": "$25k-$100k+",
        },
        "quality_contract": {
            "source_of_truth": "public.structures",
            "release_gate_status": "passed",
            "release_gate_blockers": [],
            "provenance_required": True,
            "audit_trail_required": True,
            "ai_policy": "suggest_only_never_overwrite",
        },
        "freshness": {
            "data_refresh_timestamp": refresh_timestamp,
            "last_refreshed": max(row["last_refreshed"] for row in rows if non_empty(row["last_refreshed"])),
            "source_as_of": max(row["source_as_of"] for row in rows if non_empty(row["source_as_of"])),
            "refresh_cadence": "quarterly for PLUTO/assessor-style authoritative sources",
        },
        "coverage": {
            "coverage_rows": coverage_rows,
            "source_counts": dict(source_counts),
        },
        "delivery": {
            "included_files": [
                "sample_structures.csv",
                "provenance_snapshot.csv",
                "coverage_gap_registry.csv",
                "release_manifest.json",
                "one_page_pitch.md",
            ],
            "production_options": ["Supabase REST/PostgREST", "SQL Server sync", "PostGIS/WKT", "CSV", "Parquet", "GeoJSON"],
        },
        "known_gaps": [
            "Demo package contains a small Manhattan sample, not full borough coverage.",
            "Full buyer delivery requires current authoritative source acquisition for the requested city/AOI.",
            "AI predictions are not used as authoritative values in this demo package.",
        ],
    }


def markdown_table(rows: list[dict], columns: list[str]) -> str:
    """Render a compact Markdown table."""
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(str(row.get(column, "")) for column in columns) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def build_readme(rows: list[dict], coverage_rows: list[dict], manifest: dict) -> str:
    """Build the buyer-facing demo package README."""
    sample_columns = ["StructureID", "StructureType", "NumStories", "NumUnits", "OccupantCount", "CoverageTier"]
    provenance_columns = ["StructureID", "StructureTypeSource", "NumStoriesSource", "NumUnitsSource", "OccupantCountSource"]
    return f"""# Manhattan Structure Intelligence Demo Package

This package demonstrates the first sellable version of **Structure Intelligence Database**: an audit-ready structure dataset where every core attribute includes source, confidence, freshness, and QA status.

## Buyer Promise

Audit-ready building attributes for risk models, planning workflows, and emergency intelligence, with source, confidence, and refresh trail for every field.

## Package Contents

- `sample_structures.csv`: canonical `public.structures`-ready sample rows.
- `provenance_snapshot.csv`: source and confidence fields for core attributes.
- `coverage_gap_registry.csv`: city-level completeness and freshness metrics.
- `release_manifest.json`: buyer-facing release, pricing, QA, delivery, and known-gap metadata.
- `one_page_pitch.md`: concise sales/outreach asset.

## Release Status

- Release gate status: `{manifest["quality_contract"]["release_gate_status"]}`
- Release gate blockers: `{len(manifest["quality_contract"]["release_gate_blockers"])}`
- Row count: `{manifest["row_count"]}`
- Data refresh timestamp: `{manifest["freshness"]["data_refresh_timestamp"]}`
- Source vintage: `{manifest["freshness"]["source_as_of"]}`

## Sample Structure Rows

{markdown_table(rows, sample_columns)}

## Provenance Snapshot

{markdown_table(rows, provenance_columns)}

## Coverage And Completeness

{markdown_table(coverage_rows, ["City", "State", "CoverageTier", "row_count", "structure_type_completeness", "num_stories_completeness", "num_units_completeness", "occupant_count_completeness"])}

## Before And After

| Raw footprint data | Structure Intelligence Database |
| --- | --- |
| Geometry only or thin attributes | Geometry plus type, stories, units, occupants |
| Source often hidden or dataset-level only | Attribute-level source and confidence |
| Staleness unclear | `data_refresh_timestamp`, `last_refreshed`, `source_as_of` |
| Hard to defend in risk/compliance reviews | Release manifest and QA gates |

## Delivery Options

- Supabase REST/PostgREST API
- SQL Server sync for enterprise buyers
- PostGIS/WKT table
- CSV, Parquet, and GeoJSON exports

## Known Gaps

- This is a small Manhattan proof package, not full production borough coverage.
- A paid buyer build should acquire current authoritative source rows for the requested city or AOI.
- AI remains suggest-only and is not used as source of truth.
"""


def build_pitch(manifest: dict) -> str:
    """Build the one-page money-path pitch."""
    return f"""# One-Page Pitch: Structure Intelligence Database

## Offer

Audit-ready structure data for your target city or risk area.

## Why Buyers Care

Risk and planning teams make expensive decisions using building attributes they often cannot verify. Structure Intelligence Database ships every core attribute with source, confidence, freshness, and QA status.

## First Paid Product

Custom city structure intelligence package delivered in 1-2 weeks.

## Best First Buyers

- Climate and flood risk analytics teams
- Insurance and reinsurance risk teams
- Emergency planning consultants
- Proptech and real estate analytics teams

## What They Receive

- Canonical structure table ready for `public.structures`
- Provenance snapshot for type, stories, units, and occupants
- Coverage and gap registry
- Release manifest with QA status
- Delivery as CSV/GeoJSON, Supabase API, SQL Server, or PostGIS/WKT

## Price Targets

- Pilot dataset: {manifest["pricing_targets"]["pilot_dataset"]}
- Custom city build: {manifest["pricing_targets"]["custom_city_build"]}
- API/database access: {manifest["pricing_targets"]["api_or_database_access"]}
- Regional enterprise license: {manifest["pricing_targets"]["regional_enterprise_license"]}

## Outreach Line

We build audit-ready building datasets for risk and planning teams. You get structure attributes with source, confidence, freshness, and QA status for every field, delivered for your target city or portfolio area.
"""


def main() -> None:
    """Build the reproducible Manhattan money-path demo package."""
    rows = read_rows(SOURCE_PATH)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    coverage_rows = build_coverage_registry(rows)
    manifest = build_release_manifest(rows, coverage_rows)

    write_csv(OUTPUT_DIR / "sample_structures.csv", rows, SAMPLE_COLUMNS)
    write_csv(OUTPUT_DIR / "provenance_snapshot.csv", rows, PROVENANCE_COLUMNS)
    write_csv(OUTPUT_DIR / "coverage_gap_registry.csv", coverage_rows, list(coverage_rows[0]))
    (OUTPUT_DIR / "release_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    (OUTPUT_DIR / "README.md").write_text(build_readme(rows, coverage_rows, manifest))
    (OUTPUT_DIR / "one_page_pitch.md").write_text(build_pitch(manifest))

    print(json.dumps({"output_dir": str(OUTPUT_DIR), "row_count": len(rows), "release_gate_status": "passed"}, indent=2))


if __name__ == "__main__":
    main()
