from __future__ import annotations

from collections import defaultdict

from structures_pipeline.utils import json_safe


ATTRIBUTE_SPECS = {
    "structure_type": (
        "StructureType",
        "StructureTypeSource",
        "StructureTypeConfidence",
        None,
    ),
    "num_stories": (
        "NumStories",
        "NumStoriesSource",
        "NumStoriesConfidence",
        None,
    ),
    "num_units": (
        "NumUnits",
        "NumUnitsSource",
        "NumUnitsConfidence",
        None,
    ),
    "occupant_count": (
        "OccupantCount",
        "OccupantCountSource",
        "OccupantCountConfidence",
        "OccupantCountMethod",
    ),
    "footprint_area_m2": (
        "FootprintArea_m2",
        "FootprintSource",
        None,
        "source_geometry",
    ),
}

RELATIONSHIP_TYPES = ("parcel", "ward", "hazard", "infrastructure")
PREDICTION_FIELDS = {
    "structure_type": "PredictedStructureType",
    "num_units": "PredictedNumUnits",
    "num_stories": "PredictedNumStories",
    "occupant_count": "PredictedOccupantCount",
}


def _attribute_profile(structure: dict, spec: tuple[str, str, str | None, str | None]) -> dict:
    """Build a stable value/source/confidence/method profile for one attribute."""
    value_field, source_field, confidence_field, method_field = spec
    method = structure.get(method_field) if method_field and method_field in structure else method_field
    return {
        "value": json_safe(structure.get(value_field)),
        "source": json_safe(structure.get(source_field)),
        "confidence": json_safe(structure.get(confidence_field)) if confidence_field else None,
        "method": json_safe(method),
    }


def build_structure_passport(
    structure: dict,
    *,
    versions: list[dict] | None = None,
    changes: list[dict] | None = None,
    conflicts: list[dict] | None = None,
    ai_suggestions: list[dict] | None = None,
    quality_issues: list[dict] | None = None,
    relationships: list[dict] | None = None,
) -> dict:
    """Assemble a bounded, user-facing audit profile without blending AI into truth."""
    if not structure.get("StructureID"):
        raise ValueError("Structure Passport requires StructureID")

    grouped_relationships: dict[str, list[dict]] = defaultdict(list)
    for relationship in relationships or []:
        relationship_type = str(
            relationship.get("relationship_type")
            or relationship.get("RelationshipType")
            or ""
        ).lower()
        if relationship_type in RELATIONSHIP_TYPES:
            grouped_relationships[relationship_type].append(json_safe(relationship))

    unresolved = [
        json_safe(issue)
        for issue in (quality_issues or [])
        if str(issue.get("status", "open")).lower() == "open"
    ]
    geometry_history = [
        {
            "source_run_id": version.get("source_run_id"),
            "source_as_of": version.get("source_as_of"),
            "recorded_at": version.get("recorded_at"),
            "record_checksum": version.get("record_checksum"),
            "geometry": version.get("geometry") or version.get("geometry_wkt"),
        }
        for version in (versions or [])[:100]
    ]

    return json_safe(
        {
            "schema_version": "1.0",
            "StructureID": structure["StructureID"],
            "current": {
                "city": structure.get("City"),
                "state": structure.get("State"),
                "country": structure.get("Country"),
                "coverage_tier": structure.get("CoverageTier"),
                "geometry": structure.get("geometry") or structure.get("geometry_wkt"),
                "load_source": structure.get("LoadSource"),
                "raw_data_source": structure.get("RawDataSource"),
                "source_authority": structure.get("SourceAuthority"),
                "source_family": structure.get("SourceFamily"),
                "provenance_tier": structure.get("ProvenanceTier"),
            },
            "attributes": {
                name: _attribute_profile(structure, spec)
                for name, spec in ATTRIBUTE_SPECS.items()
            },
            "freshness": {
                "source_as_of": structure.get("source_as_of"),
                "last_refreshed": structure.get("last_refreshed"),
                "data_refresh_timestamp": structure.get("data_refresh_timestamp"),
            },
            "geometry_history": geometry_history,
            "conflicts": [json_safe(row) for row in (conflicts or [])],
            "change_timeline": [json_safe(row) for row in (changes or [])[:100]],
            "ai_suggestions": [json_safe(row) for row in (ai_suggestions or [])],
            "qa": {
                "status": structure.get("qa_status")
                or ("warning" if unresolved else "passed"),
                "unresolved_warning_count": len(unresolved),
                "issues": [json_safe(row) for row in (quality_issues or [])],
            },
            "relationships": {
                relationship_type: grouped_relationships[relationship_type]
                for relationship_type in RELATIONSHIP_TYPES
            },
        }
    )


def ai_suggestion_rows_from_canonical(row: dict) -> list[dict]:
    """Extract complete suggest-only model outputs for separate database storage."""
    suggestions = []
    for attribute_name, field_name in PREDICTION_FIELDS.items():
        value = row.get(field_name)
        if value is None:
            continue
        try:
            if value != value:
                continue
        except (TypeError, ValueError):
            pass
        required = {
            "model_name": row.get("PredictionModelName"),
            "model_version": row.get("PredictionModelVersion"),
            "prediction_kind": row.get("PredictionKind"),
            "confidence": row.get("PredictionConfidence"),
            "disclosure_level": row.get("AIDisclosureLevel"),
        }
        missing = [name for name, item in required.items() if item in (None, "")]
        if missing:
            raise ValueError(
                f"AI suggestion for {field_name} is missing provenance: {missing}"
            )
        suggestions.append(
            {
                "structure_id": row["StructureID"],
                "attribute_name": attribute_name,
                "suggested_value": json_safe(value),
                **required,
                "features_used": json_safe(row.get("PredictionFeaturesUsed") or []),
                "suppression_reason": json_safe(row.get("PredictionSuppressionReason")),
                "status": "suggested",
                "source_run_id": row.get("source_run_id"),
            }
        )
    return suggestions
