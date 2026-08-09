from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from structures_pipeline.config import PipelineConfig
from structures_pipeline.utils import json_safe, utc_now_iso


OBSERVATION_FIELDS = {
    "StructureType": "structure_type",
    "StructureTypeSource": "structure_type_source",
    "StructureTypeConfidence": "structure_type_confidence",
    "NumUnits": "num_units",
    "NumUnitsSource": "num_units_source",
    "NumUnitsConfidence": "num_units_confidence",
    "NumStories": "num_stories",
    "NumStoriesSource": "num_stories_source",
    "NumStoriesConfidence": "num_stories_confidence",
    "FootprintArea_m2": "footprint_area_m2",
    "FootprintArea_sqft": "footprint_area_sqft",
    "OccupantCount": "occupant_count",
    "OccupantCountSource": "occupant_count_source",
    "OccupantCountMethod": "occupant_count_method",
    "OccupantCountConfidence": "occupant_count_confidence",
    "LoadSource": "load_source",
    "FootprintSource": "footprint_source",
}

DELTA_FIELDS = (
    "StructureType",
    "StructureTypeSource",
    "StructureTypeConfidence",
    "NumUnits",
    "NumUnitsSource",
    "NumUnitsConfidence",
    "NumStories",
    "NumStoriesSource",
    "NumStoriesConfidence",
    "FootprintArea_m2",
    "FootprintArea_sqft",
    "OccupantCount",
    "OccupantCountSource",
    "OccupantCountMethod",
    "OccupantCountConfidence",
    "RawDataSource",
    "FootprintSource",
    "CoverageTier",
    "geometry_wkt",
)


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 checksum without loading the source file into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_checksum(payload: dict) -> str:
    """Hash normalized values deterministically for idempotency and compact comparisons."""
    encoded = json.dumps(
        json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_source_object_row(config: PipelineConfig, source_run: dict) -> dict:
    """Build the immutable object-storage reference required by normalized staging."""
    source_object_id = config.refresh_source_object_id
    object_uri = config.refresh_source_object_uri
    checksum = config.refresh_source_object_checksum
    if config.refresh_require_archive and (not object_uri or not checksum):
        raise ValueError(
            "Production refresh requires refresh_source_object_uri and "
            "refresh_source_object_checksum"
        )
    checksum = checksum or stable_checksum(
        {
            "source_run_id": source_run["source_run_id"],
            "source_as_of": source_run.get("source_as_of"),
        }
    )
    source_object_id = source_object_id or f"sha256:{checksum}"
    object_uri = object_uri or f"local-staged://{source_run['source_run_id']}"
    prefix = f"supabase://{config.refresh_archive_bucket}/"
    object_path = object_uri[len(prefix):] if object_uri.startswith(prefix) else object_uri.rsplit("/", 1)[-1]
    return {
        "source_object_id": source_object_id,
        "bucket_id": config.refresh_archive_bucket,
        "object_path": object_path,
        "object_uri": object_uri,
        "checksum_sha256": checksum,
        "content_type": config.refresh_metadata.get("source_content_type"),
        "byte_size": config.refresh_metadata.get("source_byte_size"),
        "source_as_of": source_run.get("source_as_of"),
        "archive_status": "registered",
        "uploaded_at": source_run["started_at"],
        "verified_at": None,
        "metadata": {
            "source_name": source_run["source_name"],
            "city": source_run.get("city"),
            "state": source_run.get("state"),
        },
    }


def _present(value):
    """Convert pandas nulls to None while retaining valid scalar values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return json_safe(value)


def build_observation_rows(
    source_frame: gpd.GeoDataFrame,
    source_run: dict,
    source_object: dict,
    config: PipelineConfig,
) -> list[dict]:
    """Normalize a source frame into compact staging rows with transient WKT."""
    if source_frame.empty:
        return []
    frame = (
        source_frame.to_crs(epsg=4326)
        if source_frame.crs and source_frame.crs.to_epsg() != 4326
        else source_frame
    )
    geometry_values = frame.geometry.to_wkt(rounding_precision=-1)
    loaded_at = utc_now_iso()
    rows: list[dict] = []
    for position, (index, row) in enumerate(frame.iterrows()):
        geometry_wkt = geometry_values.iloc[position] if row.geometry is not None else None
        structure_id = str(_present(row.get("StructureID")) or f"{source_run['source_run_id']}_{index}")
        raw_record_id = str(
            _present(row.get("raw_record_id"))
            or _present(row.get("RawRecordID"))
            or structure_id
        )
        observation = {
            "source_run_id": source_run["source_run_id"],
            "raw_record_id": raw_record_id,
            "source_object_id": source_object["source_object_id"],
            "source_row_number": position + 1,
            "structure_id": structure_id,
            "raw_data_source": str(_present(row.get("RawDataSource")) or source_run["source_name"]),
            "source_authority": str(
                _present(row.get("SourceAuthority"))
                or config.refresh_metadata.get("source_authority")
                or source_run["source_name"]
            ),
            "source_family": str(
                _present(row.get("SourceFamily")) or source_run["source_family"]
            ),
            "provenance_tier": str(
                _present(row.get("ProvenanceTier"))
                or config.refresh_metadata.get("provenance_tier")
                or "documented_source"
            ),
            "source_as_of": str(
                _present(row.get("source_as_of")) or source_run["source_as_of"]
            ),
            "city": str(_present(row.get("City")) or config.refresh_city or ""),
            "state": str(_present(row.get("State")) or config.refresh_state or ""),
            "country": str(_present(row.get("Country")) or config.country),
            "coverage_tier": str(_present(row.get("CoverageTier")) or "Unassigned"),
            "geometry_wkt": geometry_wkt,
            "loaded_at": loaded_at,
            "data_refresh_timestamp": source_run["data_refresh_timestamp"],
        }
        for canonical_name, observation_name in OBSERVATION_FIELDS.items():
            observation[observation_name] = _present(row.get(canonical_name))
        checksum_payload = {
            key: value
            for key, value in observation.items()
            if key not in {"record_checksum", "loaded_at", "data_refresh_timestamp"}
        }
        observation["record_checksum"] = stable_checksum(checksum_payload)
        rows.append(observation)
    return rows


def observation_to_canonical(row: dict) -> dict:
    """Convert one normalized observation into the canonical Python field contract."""
    geometry_wkt = row.get("geometry_wkt")
    if geometry_wkt is None and isinstance(row.get("geom"), dict):
        geometry_wkt = shape(row["geom"]).wkt
    payload = {
        "StructureID": row.get("structure_id"),
        "City": row.get("city"),
        "State": row.get("state"),
        "Country": row.get("country"),
        "CoverageTier": row.get("coverage_tier"),
        "geometry_wkt": geometry_wkt,
        "RawDataSource": row.get("raw_data_source"),
        "SourceAuthority": row.get("source_authority"),
        "SourceFamily": row.get("source_family"),
        "ProvenanceTier": row.get("provenance_tier"),
        "source_as_of": row.get("source_as_of"),
        "source_run_id": row.get("source_run_id"),
        "source_object_id": row.get("source_object_id"),
        "raw_record_id": row.get("raw_record_id"),
        "record_checksum": row.get("record_checksum"),
    }
    for canonical_name, observation_name in OBSERVATION_FIELDS.items():
        payload[canonical_name] = row.get(observation_name)
    return payload


def compact_field_deltas(after: dict, before: dict | None) -> dict:
    """Return only changed field values instead of full before/after record copies."""
    before = before or {}
    deltas = {}
    for field in DELTA_FIELDS:
        before_value = _present(before.get(field))
        after_value = _present(after.get(field))
        if before_value != after_value:
            deltas[field] = {"before": before_value, "after": after_value}
    return deltas
