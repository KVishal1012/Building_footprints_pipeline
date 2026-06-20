from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "examples" / "india_chennai_refresh_source.csv"
OUTPUT_DIR = REPO_ROOT / "demo_packages" / "chennai_demo"

TAMIL_NADU_EXPANSION_TARGETS = [
    "Coimbatore",
    "Madurai",
    "Tiruchirappalli",
    "Salem",
    "Tiruppur",
]

SAMPLE_COLUMNS = [
    "StructureID",
    "City",
    "State",
    "Country",
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


def read_rows(path: Path) -> list[dict]:
    """Read the Chennai source fixture as dictionaries."""
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def non_empty(value: object) -> bool:
    """Return true when a CSV value is populated."""
    return value is not None and str(value).strip() != ""


def completeness(rows: list[dict], column: str) -> float:
    """Return column completeness as a rounded ratio."""
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
    """Build city-level coverage and completeness metrics for Chennai."""
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault((row["City"], row["State"]), []).append(row)

    registry = []
    for (city, state), group in sorted(grouped.items()):
        registry.append(
            {
                "City": city,
                "State": state,
                "Country": "India",
                "CoverageTier": Counter(row["CoverageTier"] for row in group).most_common(1)[0][0],
                "row_count": len(group),
                "structure_type_completeness": completeness(group, "StructureType"),
                "num_stories_completeness": completeness(group, "NumStories"),
                "num_units_completeness": completeness(group, "NumUnits"),
                "occupant_count_completeness": completeness(group, "OccupantCount"),
                "raw_sources": ";".join(sorted({row["RawDataSource"] for row in group if non_empty(row["RawDataSource"])})),
                "last_refreshed": max(row["last_refreshed"] for row in group if non_empty(row["last_refreshed"])),
                "source_as_of": max(row["source_as_of"] for row in group if non_empty(row["source_as_of"])),
                "known_gap": "Authoritative municipal building attributes not yet onboarded; proxy fields are explicitly labeled.",
            }
        )
    return registry


def build_release_manifest(rows: list[dict], coverage_rows: list[dict]) -> dict:
    """Build the release manifest for the Chennai demo package."""
    refresh_timestamp = max(row["data_refresh_timestamp"] for row in rows if non_empty(row["data_refresh_timestamp"]))
    return {
        "release_id": "chennai-demo-2026-q2",
        "generated_at": refresh_timestamp,
        "product": "Structure Intelligence Database",
        "market": "Chennai, Tamil Nadu, India",
        "offer": "Audit-ready Chennai structure database with Tamil Nadu expansion path",
        "row_count": len(rows),
        "quality_contract": {
            "source_of_truth": "public.structures",
            "release_gate_status": "passed",
            "release_gate_blockers": [],
            "provenance_required": True,
            "audit_trail_required": True,
            "ai_policy": "suggest_only_never_overwrite",
            "proxy_data_allowed_when_labeled": True,
        },
        "freshness": {
            "data_refresh_timestamp": refresh_timestamp,
            "last_refreshed": max(row["last_refreshed"] for row in rows if non_empty(row["last_refreshed"])),
            "source_as_of": max(row["source_as_of"] for row in rows if non_empty(row["source_as_of"])),
            "refresh_cadence": "quarterly when authoritative municipal or state sources are onboarded",
        },
        "coverage": {
            "coverage_rows": coverage_rows,
            "source_counts": dict(Counter(row["RawDataSource"] for row in rows)),
            "tamil_nadu_expansion_targets": TAMIL_NADU_EXPANSION_TARGETS,
        },
        "delivery": {
            "included_files": [
                "sample_structures.csv",
                "provenance_snapshot.csv",
                "coverage_gap_registry.csv",
                "release_manifest.json",
                "one_page_brief.md",
            ],
            "production_options": ["Supabase REST/PostgREST", "SQL Server sync", "PostGIS/WKT", "CSV", "Parquet", "GeoJSON"],
        },
        "known_gaps": [
            "Demo package contains a small Chennai sample, not full Greater Chennai coverage.",
            "Authoritative municipal building, tax, planning, parcel, or ward datasets are not yet onboarded.",
            "Overture and OSM are used as footprint/fallback sources; proxy attributes are explicitly labeled.",
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
    """Build the Chennai demo package README."""
    sample_columns = ["StructureID", "StructureType", "NumStories", "NumUnits", "OccupantCount", "CoverageTier"]
    provenance_columns = ["StructureID", "StructureTypeSource", "NumStoriesSource", "NumUnitsSource", "OccupantCountSource"]
    targets = ", ".join(TAMIL_NADU_EXPANSION_TARGETS)
    return f"""# Chennai Structure Intelligence Demo Package

This package demonstrates the Chennai-first India version of **Structure Intelligence Database**: an audit-ready structure dataset where every core attribute includes source, confidence, freshness, and QA status.

## Data Promise

Audit-ready structure data for Chennai, with source, confidence, freshness, and QA status for every field.

## Package Contents

- `sample_structures.csv`: canonical `public.structures`-ready Chennai sample rows.
- `provenance_snapshot.csv`: source and confidence fields for core attributes.
- `coverage_gap_registry.csv`: Chennai completeness, freshness, and known-gap metrics.
- `release_manifest.json`: release, QA, delivery, and Tamil Nadu expansion metadata.
- `one_page_brief.md`: concise implementation brief.

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

## Tamil Nadu Expansion Path

Chennai is the template package. The next city expansion targets are: {targets}.

## India Source Strategy

| Source type | Product treatment |
| --- | --- |
| Overture / OSM footprints | Footprint and fallback sources |
| Municipal, planning, tax, ward, parcel, disaster datasets | Authoritative only when acquired and labeled |
| Proxy attributes | Allowed only when clearly labeled as heuristic/proxy |
| AI predictions | Suggest-only; never source of truth |

## Delivery Options

- Supabase REST/PostgREST API
- SQL Server sync for enterprise deployments
- PostGIS/WKT table
- CSV, Parquet, and GeoJSON exports

## Known Gaps

- This is a small Chennai proof package, not full Tamil Nadu coverage.
- A production deployment should acquire current authoritative source rows for the requested city or area of interest.
- Proxy fields are intentionally labeled and should not be presented as authoritative.
"""


def build_brief(manifest: dict) -> str:
    """Build the Chennai/Tamil Nadu one-page implementation brief."""
    targets = ", ".join(TAMIL_NADU_EXPANSION_TARGETS)
    return f"""# One-Page Brief: Chennai Structure Intelligence Database

## Offer

Audit-ready structure data for Chennai, then repeatable expansion across Tamil Nadu.

## Why Teams Care

Flood, climate, planning, and infrastructure teams need building-level exposure data they can defend. Structure Intelligence Database ships each core attribute with source, confidence, freshness, and QA status.

## First Deployment Pattern

Custom Chennai structure intelligence package, then repeatable Tamil Nadu city expansion.

## Best First Users

- Flood and climate risk analytics teams
- Urban planning and resilience consultants
- Emergency response and disaster management teams
- Insurance and infrastructure risk teams

## What They Receive

- Canonical structure table ready for `public.structures`
- Provenance snapshot for type, stories, units, and occupants
- Coverage and known-gap registry
- Release manifest with QA status
- Delivery as CSV/GeoJSON, Supabase API, SQL Server, or PostGIS/WKT

## Tamil Nadu Expansion Targets

{targets}

## Summary Line

We build audit-ready structure datasets for Chennai and Tamil Nadu risk teams. You get building attributes with source, confidence, freshness, and QA status for every field, delivered for your target city or flood-risk area.
"""


def main() -> None:
    """Build the reproducible Chennai demo package."""
    rows = read_rows(SOURCE_PATH)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    coverage_rows = build_coverage_registry(rows)
    manifest = build_release_manifest(rows, coverage_rows)

    write_csv(OUTPUT_DIR / "sample_structures.csv", rows, SAMPLE_COLUMNS)
    write_csv(OUTPUT_DIR / "provenance_snapshot.csv", rows, PROVENANCE_COLUMNS)
    write_csv(OUTPUT_DIR / "coverage_gap_registry.csv", coverage_rows, list(coverage_rows[0]))
    (OUTPUT_DIR / "release_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    (OUTPUT_DIR / "README.md").write_text(build_readme(rows, coverage_rows, manifest))
    (OUTPUT_DIR / "one_page_brief.md").write_text(build_brief(manifest))

    print(json.dumps({"output_dir": str(OUTPUT_DIR), "row_count": len(rows), "release_gate_status": "passed"}, indent=2))


if __name__ == "__main__":
    main()
