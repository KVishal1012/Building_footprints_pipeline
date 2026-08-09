from structures_pipeline.passport import (
    ai_suggestion_rows_from_canonical,
    build_structure_passport,
)


def test_structure_passport_separates_authoritative_values_from_ai():
    passport = build_structure_passport(
        {
            "StructureID": "chennai-1",
            "City": "Chennai",
            "State": "Tamil Nadu",
            "Country": "India",
            "CoverageTier": "Tier 4",
            "StructureType": "residential",
            "StructureTypeSource": "openstreetmap:building",
            "StructureTypeConfidence": 0.8,
            "NumStories": None,
            "NumStoriesSource": None,
            "data_refresh_timestamp": "2026-07-28T12:00:00+00:00",
            "source_as_of": "2026-07-01",
            "qa_status": "passed",
            "geometry_wkt": "POLYGON ((0 0, 0 1, 1 1, 0 0))",
        },
        ai_suggestions=[
            {
                "attribute_name": "NumStories",
                "suggested_value": 3,
                "model_name": "stories-baseline",
                "confidence": 0.72,
            }
        ],
    )

    assert passport["attributes"]["structure_type"]["value"] == "residential"
    assert passport["attributes"]["num_stories"]["value"] is None
    assert passport["ai_suggestions"][0]["suggested_value"] == 3
    assert passport["current"].get("PredictedNumStories") is None


def test_structure_passport_groups_relationships_and_reports_open_warnings():
    passport = build_structure_passport(
        {"StructureID": "chennai-2", "qa_status": "warning"},
        quality_issues=[
            {"status": "open", "severity": "warning", "message": "Ward link pending"},
            {"status": "resolved", "severity": "info", "message": "Geometry repaired"},
        ],
        relationships=[
            {"relationship_type": "ward", "related_record_id": "ward-174"},
            {"relationship_type": "hazard", "related_record_id": "flood-10yr"},
        ],
    )

    assert passport["qa"]["unresolved_warning_count"] == 1
    assert passport["relationships"]["ward"][0]["related_record_id"] == "ward-174"
    assert passport["relationships"]["hazard"][0]["related_record_id"] == "flood-10yr"
    assert passport["relationships"]["parcel"] == []


def test_structure_passport_requires_stable_identity():
    try:
        build_structure_passport({})
    except ValueError as exc:
        assert "StructureID" in str(exc)
    else:
        raise AssertionError("Passport accepted a structure without identity")


def test_ai_suggestion_requires_complete_model_provenance():
    row = {
        "StructureID": "chennai-3",
        "PredictedNumStories": 4,
        "PredictionModelName": "stories-baseline",
        "PredictionModelVersion": "1.0",
        "PredictionKind": "suggestion",
        "PredictionConfidence": 0.81,
        "PredictionFeaturesUsed": ["footprint_area"],
        "AIDisclosureLevel": "estimated",
        "source_run_id": "run-1",
    }

    suggestions = ai_suggestion_rows_from_canonical(row)

    assert suggestions[0]["attribute_name"] == "num_stories"
    assert suggestions[0]["suggested_value"] == 4
    assert suggestions[0]["model_name"] == "stories-baseline"
