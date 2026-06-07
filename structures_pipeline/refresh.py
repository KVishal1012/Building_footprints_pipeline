from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Iterable

import geopandas as gpd
import pandas as pd
import requests
from shapely import wkt

from structures_pipeline.config import PipelineConfig
from structures_pipeline.coverage import build_gap_registry
from structures_pipeline.release import build_release_manifest
from structures_pipeline.utils import json_safe, utc_now_iso
from structures_pipeline.validation import validate_output

CHANGE_TYPES = {"insert", "update", "delete_candidate", "unchanged"}
RAW_REQUIRED_FIELDS = [
    "raw_record_id",
    "source_run_id",
    "raw_data_source",
    "source_authority",
    "source_family",
    "source_as_of",
    "city",
    "state",
    "geometry_wkt",
    "raw_payload",
    "loaded_at",
    "data_refresh_timestamp",
]

CANONICAL_TO_DB_COLUMNS = {
    "StructureID": "structure_id",
    "City": "city",
    "State": "state",
    "Country": "country",
    "CoverageTier": "coverage_tier",
    "geometry_wkt": "geometry_wkt",
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
    "RawDataSource": "raw_data_source",
    "FootprintSource": "footprint_source",
    "created_at": "created_at",
    "updated_at": "updated_at",
    "updated_by": "updated_by",
    "change_log": "change_log",
    "data_refresh_timestamp": "data_refresh_timestamp",
    "last_refreshed": "last_refreshed",
    "source_as_of": "source_as_of",
}
DB_TO_CANONICAL_COLUMNS = {value: key for key, value in CANONICAL_TO_DB_COLUMNS.items()}


# Convert pandas/numpy values into JSON-compatible primitives for database writes.
def _json_ready(value):
    """Convert pandas/numpy values into JSON-compatible primitives for database writes."""
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return json_safe(value)


@dataclass
class InMemoryRefreshStore:
    source_runs: dict[str, dict] = field(default_factory=dict)
    raw_structures: list[dict] = field(default_factory=list)
    change_log: list[dict] = field(default_factory=list)
    promotion_failures: list[dict] = field(default_factory=list)
    canonical_structures: dict[str, dict] = field(default_factory=dict)
    coverage_registry: dict[tuple[str, str], dict] = field(default_factory=dict)
    release_manifests: dict[str, dict] = field(default_factory=dict)

    # Persist or replace one source run metadata row.
    def upsert_source_run(self, row: dict) -> None:
        """Persist or replace one source run metadata row."""
        self.source_runs[row["source_run_id"]] = deepcopy(row)

    # Append staged raw rows for a source run.
    def insert_raw_rows(self, rows: Iterable[dict]) -> None:
        """Append staged raw rows for a source run."""
        self.raw_structures.extend(deepcopy(list(rows)))

    # Return raw rows staged for one source run.
    def raw_rows_for_run(self, source_run_id: str) -> list[dict]:
        """Return raw rows staged for one source run."""
        return [deepcopy(row) for row in self.raw_structures if row["source_run_id"] == source_run_id]

    # Append change detector results.
    def insert_change_rows(self, rows: Iterable[dict]) -> None:
        """Append change detector results."""
        self.change_log.extend(deepcopy(list(rows)))

    # Return detected change rows for one source run.
    def changes_for_run(self, source_run_id: str) -> list[dict]:
        """Return detected change rows for one source run."""
        return [deepcopy(row) for row in self.change_log if row["source_run_id"] == source_run_id]

    # Append rows blocked by promotion QA.
    def insert_promotion_failures(self, rows: Iterable[dict]) -> None:
        """Append rows blocked by promotion QA."""
        self.promotion_failures.extend(deepcopy(list(rows)))

    # Upsert approved canonical records.
    def upsert_canonical_rows(self, rows: Iterable[dict]) -> None:
        """Upsert approved canonical records."""
        for row in rows:
            self.canonical_structures[row["StructureID"]] = deepcopy(row)

    # Return canonical records as dictionaries.
    def canonical_rows(self) -> list[dict]:
        """Return canonical records as dictionaries."""
        return [deepcopy(row) for row in self.canonical_structures.values()]

    # Store coverage registry rows keyed by city/state.
    def upsert_coverage_rows(self, rows: Iterable[dict]) -> None:
        """Store coverage registry rows keyed by city/state."""
        for row in rows:
            self.coverage_registry[(str(row["City"]), str(row["State"]))] = deepcopy(row)

    # Store one release manifest snapshot.
    def upsert_release_manifest(self, manifest: dict) -> None:
        """Store one release manifest snapshot."""
        self.release_manifests[manifest["release_id"]] = deepcopy(manifest)


class SupabaseRefreshStore:
    """Persist refresh workflow rows through Supabase's PostgREST API."""

    def __init__(
        self,
        config: PipelineConfig,
        *,
        session: requests.Session | None = None,
        service_key: str | None = None,
    ) -> None:
        self.config = config
        self.supabase_url = (config.supabase_url or "").rstrip("/")
        if not self.supabase_url:
            raise ValueError("Supabase store requires config.supabase_url")
        self.service_key = service_key or os.environ.get(config.supabase_service_role_env)
        if not self.service_key:
            raise ValueError(f"Missing Supabase service key in {config.supabase_service_role_env}")
        self.session = session or requests.Session()

    # Return a schema/table pair from the configured canonical database contract.
    def _table_parts(self, config_key: str) -> tuple[str, str]:
        """Return a schema/table pair from the configured canonical database contract."""
        table_name = self.config.canonical_database[config_key]
        schema, _, table = table_name.partition(".")
        return schema or "public", table or schema

    # Build auth and schema headers for one PostgREST request.
    def _headers(self, schema: str, *, write: bool) -> dict:
        """Build auth and schema headers for one PostgREST request."""
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        profile = "Content-Profile" if write else "Accept-Profile"
        headers[profile] = schema
        return headers

    # Execute a PostgREST request and return decoded JSON when present.
    def _request(
        self,
        method: str,
        config_key: str,
        *,
        payload=None,
        params: dict | None = None,
        upsert_key: str | None = None,
    ):
        """Execute a PostgREST request and return decoded JSON when present."""
        schema, table = self._table_parts(config_key)
        request_params = dict(params or {})
        headers = self._headers(schema, write=method.upper() != "GET")
        if upsert_key:
            request_params["on_conflict"] = upsert_key
            headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        elif method.upper() != "GET":
            headers["Prefer"] = "return=minimal"
        response = self.session.request(
            method,
            f"{self.supabase_url}/rest/v1/{table}",
            headers=headers,
            params=request_params,
            json=_json_ready(payload) if payload is not None else None,
            timeout=int(self.config.request_timeout_sec),
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase {method} {schema}.{table} failed: {response.status_code} {response.text}")
        if not response.text:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    # Persist or replace one source run metadata row.
    def upsert_source_run(self, row: dict) -> None:
        """Persist or replace one source run metadata row."""
        self._request("POST", "source_runs_table", payload=row, upsert_key="source_run_id")

    # Append staged raw rows for a source run.
    def insert_raw_rows(self, rows: Iterable[dict]) -> None:
        """Append staged raw rows for a source run."""
        rows = list(rows)
        if rows:
            self._request("POST", "raw_table", payload=rows)

    # Return raw rows staged for one source run.
    def raw_rows_for_run(self, source_run_id: str) -> list[dict]:
        """Return raw rows staged for one source run."""
        return self._request("GET", "raw_table", params={"source_run_id": f"eq.{source_run_id}"}) or []

    # Append change detector results.
    def insert_change_rows(self, rows: Iterable[dict]) -> None:
        """Append change detector results."""
        rows = list(rows)
        if rows:
            self._request("POST", "change_log_table", payload=rows)

    # Return detected change rows for one source run.
    def changes_for_run(self, source_run_id: str) -> list[dict]:
        """Return detected change rows for one source run."""
        return self._request("GET", "change_log_table", params={"source_run_id": f"eq.{source_run_id}"}) or []

    # Append rows blocked by promotion QA.
    def insert_promotion_failures(self, rows: Iterable[dict]) -> None:
        """Append rows blocked by promotion QA."""
        rows = list(rows)
        if rows:
            self._request("POST", "promotion_failures_table", payload=rows)

    # Upsert approved canonical records.
    def upsert_canonical_rows(self, rows: Iterable[dict]) -> None:
        """Upsert approved canonical records."""
        db_rows = [canonical_row_to_db(row) for row in rows]
        if db_rows:
            self._request("POST", "canonical_table", payload=db_rows, upsert_key="structure_id")

    # Return canonical records as dictionaries.
    def canonical_rows(self) -> list[dict]:
        """Return canonical records as dictionaries."""
        rows = self._request("GET", "canonical_table") or []
        return [canonical_row_from_db(row) for row in rows]

    # Store coverage registry rows keyed by city/state.
    def upsert_coverage_rows(self, rows: Iterable[dict]) -> None:
        """Store coverage registry rows keyed by city/state."""
        db_rows = [coverage_row_to_db(row) for row in rows]
        if db_rows:
            self._request("POST", "coverage_table", payload=db_rows, upsert_key="city,state")

    # Store one release manifest snapshot.
    def upsert_release_manifest(self, manifest: dict) -> None:
        """Store one release manifest snapshot."""
        row = {
            "release_id": manifest["release_id"],
            "schema_version": manifest.get("schema_version", "2.0"),
            "row_count": int(manifest.get("row_count") or 0),
            "manifest": manifest,
        }
        self._request("POST", "release_table", payload=row, upsert_key="release_id")


# Convert a canonical pipeline row into the public.structures database shape.
def canonical_row_to_db(row: dict) -> dict:
    """Convert a canonical pipeline row into the public.structures database shape."""
    db_row = {db_key: _json_ready(row.get(source_key)) for source_key, db_key in CANONICAL_TO_DB_COLUMNS.items()}
    db_row["attribute_provenance"] = {
        "structure_type": {
            "source": db_row.get("structure_type_source"),
            "confidence": db_row.get("structure_type_confidence"),
        },
        "num_units": {
            "source": db_row.get("num_units_source"),
            "confidence": db_row.get("num_units_confidence"),
        },
        "num_stories": {
            "source": db_row.get("num_stories_source"),
            "confidence": db_row.get("num_stories_confidence"),
        },
        "occupant_count": {
            "source": db_row.get("occupant_count_source"),
            "method": db_row.get("occupant_count_method"),
            "confidence": db_row.get("occupant_count_confidence"),
        },
    }
    db_row["ai_suggestions"] = {
        "structure_type": _json_ready(row.get("PredictedStructureType")),
        "num_units": _json_ready(row.get("PredictedNumUnits")),
        "num_stories": _json_ready(row.get("PredictedNumStories")),
        "occupant_count": _json_ready(row.get("PredictedOccupantCount")),
        "prediction_kind": _json_ready(row.get("PredictionKind")),
        "confidence": _json_ready(row.get("PredictionConfidence")),
    }
    return db_row


# Convert a public.structures database row back into the canonical pipeline shape.
def canonical_row_from_db(row: dict) -> dict:
    """Convert a public.structures database row back into the canonical pipeline shape."""
    converted = {canonical_key: row.get(db_key) for db_key, canonical_key in DB_TO_CANONICAL_COLUMNS.items()}
    return {**row, **converted}


# Convert gap-registry metrics into public.coverage_registry shape.
def coverage_row_to_db(row: dict) -> dict:
    """Convert gap-registry metrics into public.coverage_registry shape."""
    return {
        "city": _json_ready(row.get("City")),
        "state": _json_ready(row.get("State")),
        "coverage_tier": _json_ready(row.get("CoverageTier")),
        "row_count": int(row.get("row_count") or 0),
        "completeness": {
            "structure_type": _json_ready(row.get("structure_type_completeness")),
            "num_units": _json_ready(row.get("num_units_completeness")),
            "num_stories": _json_ready(row.get("num_stories_completeness")),
            "occupant_count": _json_ready(row.get("occupant_count_completeness")),
        },
        "source_summary": {
            "has_authoritative_source": bool(row.get("has_authoritative_source")),
            "has_nsi": bool(row.get("has_nsi")),
            "has_overture": bool(row.get("has_overture")),
            "has_osm": bool(row.get("has_osm")),
        },
        "data_refresh_timestamp": _json_ready(row.get("data_refresh_timestamp")),
        "last_refreshed": _json_ready(row.get("last_refreshed")),
        "source_as_of": _json_ready(row.get("source_as_of")),
    }


# Build the configured refresh store for local, dry-run, or production runs.
def build_refresh_store(
    config: PipelineConfig,
    store_name: str = "in_memory",
    *,
    session: requests.Session | None = None,
    service_key: str | None = None,
):
    """Build the configured refresh store for local, dry-run, or production runs."""
    if config.dry_run or store_name == "in_memory":
        return InMemoryRefreshStore()
    if store_name == "supabase":
        return SupabaseRefreshStore(config, session=session, service_key=service_key)
    raise ValueError(f"Unsupported refresh store: {store_name}")


# Build a deterministic source run id from source, location, and timestamp when not provided.
def make_source_run_id(source_name: str, city: str, state: str, started_at: str | None = None) -> str:
    """Build a deterministic source run id from source, location, and timestamp when not provided."""
    timestamp = started_at or utc_now_iso()
    slug = "_".join(str(part).lower().replace(" ", "_") for part in (source_name, city, state))
    return f"{slug}_{timestamp.replace(':', '').replace('+', 'Z')}"


# Return the configured refresh datetime stamp or create one for this run.
def refresh_timestamp(config: PipelineConfig) -> str:
    """Return the configured refresh datetime stamp or create one for this run."""
    return config.data_refresh_timestamp or utc_now_iso()


# Create the metadata row stored in staging.source_runs.
def build_source_run_row(
    source_name: str,
    city: str,
    state: str,
    config: PipelineConfig,
    *,
    source_run_id: str | None = None,
    row_count: int = 0,
    status: str = "running",
    metadata: dict | None = None,
) -> dict:
    """Create the metadata row stored in staging.source_runs."""
    started_at = utc_now_iso()
    data_refresh_timestamp = refresh_timestamp(config)
    return {
        "source_run_id": source_run_id or make_source_run_id(source_name, city, state, started_at),
        "source_name": source_name,
        "source_family": config.refresh_source_family or source_name,
        "source_as_of": config.refresh_source_as_of or config.source_version,
        "refresh_cadence": config.refresh_cadence,
        "data_refresh_timestamp": data_refresh_timestamp,
        "started_at": started_at,
        "completed_at": None,
        "status": status,
        "row_count": int(row_count),
        "metadata": json_safe(metadata or {"city": city, "state": state}),
    }


# Convert a GeoDataFrame row into a JSON-safe raw staging payload.
def _row_payload(row: pd.Series, geometry_wkt: str) -> dict:
    """Convert a GeoDataFrame row into a JSON-safe raw staging payload."""
    payload = {}
    for key, value in row.drop(labels=["geometry"], errors="ignore").to_dict().items():
        payload[key] = None if pd.isna(value) else value
    payload["geometry_wkt"] = geometry_wkt
    return json_safe(payload)


# Return the preferred canonical id from a raw payload.
def canonical_structure_id(payload: dict, fallback: str) -> str:
    """Return the preferred canonical id from a raw payload."""
    for key in ("StructureID", "structure_id", "OvertureID", "overture_id", "MicrosoftID", "raw_record_id"):
        value = payload.get(key)
        if value is not None and str(value).strip() and str(value) != "<NA>":
            return str(value)
    return fallback


# Return a string value only when it is present and not a pandas null.
def _present_text(value) -> str | None:
    """Return a string value only when it is present and not a pandas null."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text == "<NA>":
        return None
    return text


# Convert source rows into staging.raw_structures-compatible dictionaries.
def build_raw_structure_rows(
    source_frame: gpd.GeoDataFrame,
    source_run: dict,
    config: PipelineConfig,
) -> list[dict]:
    """Convert source rows into staging.raw_structures-compatible dictionaries."""
    if source_frame.empty:
        return []
    frame = source_frame.to_crs(epsg=4326) if source_frame.crs and source_frame.crs.to_epsg() != 4326 else source_frame
    rows: list[dict] = []
    loaded_at = utc_now_iso()
    for index, row in frame.iterrows():
        geom = row.geometry
        geometry_wkt = geom.wkt if geom is not None else None
        payload = _row_payload(row, geometry_wkt or "")
        fallback_id = f"{source_run['source_run_id']}_{index}"
        canonical_id = canonical_structure_id(payload, fallback_id)
        raw_record_id = str(payload.get("raw_record_id") or payload.get("RawRecordID") or canonical_id)
        rows.append(
            {
                "raw_record_id": raw_record_id,
                "source_run_id": source_run["source_run_id"],
                "raw_data_source": str(payload.get("RawDataSource") or source_run["source_name"]),
                "source_authority": str(payload.get("SourceAuthority") or source_run["source_name"]),
                "source_family": str(payload.get("SourceFamily") or source_run["source_family"]),
                "source_as_of": str(payload.get("source_as_of") or source_run["source_as_of"]),
                "city": str(payload.get("City") or config.refresh_city or ""),
                "state": str(payload.get("State") or config.refresh_state or ""),
                "geometry_wkt": geometry_wkt,
                "raw_payload": payload,
                "loaded_at": loaded_at,
                "data_refresh_timestamp": source_run["data_refresh_timestamp"],
            }
        )
    return rows


# Validate raw staging rows before delta detection.
def validate_raw_rows(rows: list[dict]) -> None:
    """Validate raw staging rows before delta detection."""
    for row in rows:
        missing = [field for field in RAW_REQUIRED_FIELDS if field not in row or row[field] in (None, "")]
        if missing:
            raise ValueError(f"Raw staging row is missing required fields: {missing}")


# Stage source rows and write source run metadata.
def run_source_refresh(
    source_name: str,
    city: str,
    state: str,
    config: PipelineConfig,
    *,
    source_frame: gpd.GeoDataFrame | None = None,
    store: InMemoryRefreshStore | None = None,
) -> dict:
    """Stage source rows and write source run metadata."""
    store = store or InMemoryRefreshStore()
    if source_frame is None:
        raise ValueError("run_source_refresh requires source_frame until live source connectors are attached")
    source_run = build_source_run_row(source_name, city, state, config, row_count=len(source_frame))
    raw_rows = build_raw_structure_rows(source_frame, source_run, config)
    validate_raw_rows(raw_rows)
    if not config.dry_run:
        store.upsert_source_run(source_run)
        store.insert_raw_rows(raw_rows)
    return {"source_run": source_run, "raw_rows": raw_rows, "store": store}


# Return true when two raw/canonical records should be treated as a spatial match.
def _spatial_match(raw_row: dict, canonical_row: dict, tolerance: float = 0.000001) -> bool:
    """Return true when two raw/canonical records should be treated as a spatial match."""
    try:
        raw_geom = wkt.loads(raw_row.get("geometry_wkt") or "")
        canonical_geom = wkt.loads(canonical_row.get("geometry_wkt") or canonical_row.get("geometry") or "")
    except Exception:
        return False
    return raw_geom.distance(canonical_geom) <= tolerance


# Find the canonical record that matches a staged raw row.
def match_canonical_row(raw_row: dict, canonical_rows: list[dict]) -> dict | None:
    """Find the canonical record that matches a staged raw row."""
    payload = raw_row["raw_payload"]
    preferred_ids = [
        payload.get("StructureID"),
        payload.get("structure_id"),
        payload.get("OvertureID"),
        payload.get("overture_id"),
        raw_row.get("raw_record_id"),
    ]
    for value in preferred_ids:
        text_value = _present_text(value)
        if text_value is None:
            continue
        for row in canonical_rows:
            structure_id = _present_text(row.get("StructureID")) or _present_text(row.get("structure_id"))
            overture_id = _present_text(row.get("OvertureID")) or _present_text(row.get("overture_id"))
            if structure_id == text_value:
                return row
            if overture_id == text_value:
                return row
    for row in canonical_rows:
        if _spatial_match(raw_row, row):
            return row
    return None


# Return changed fields between staged raw payload and canonical record.
def changed_fields(raw_payload: dict, canonical_row: dict) -> list[str]:
    """Return changed fields between staged raw payload and canonical record."""
    compare_fields = [
        "StructureType",
        "NumUnits",
        "NumStories",
        "FootprintArea_m2",
        "FootprintArea_sqft",
        "OccupantCount",
        "RawDataSource",
        "FootprintSource",
        "CoverageTier",
        "geometry_wkt",
    ]
    changed: list[str] = []
    for field in compare_fields:
        raw_value = raw_payload.get(field)
        canonical_value = canonical_row.get(field)
        if raw_value is None and canonical_value is None:
            continue
        if str(raw_value) != str(canonical_value):
            changed.append(field)
    return changed


# Build one staging.change_log row.
def build_change_row(source_run_id: str, change_type: str, raw_row: dict | None, canonical_row: dict | None) -> dict:
    """Build one staging.change_log row."""
    if change_type not in CHANGE_TYPES:
        raise ValueError(f"Unsupported change type: {change_type}")
    raw_payload = raw_row["raw_payload"] if raw_row else {}
    structure_id = canonical_structure_id(raw_payload, "") or (canonical_row or {}).get("StructureID")
    fields = changed_fields(raw_payload, canonical_row or {}) if raw_row and canonical_row else []
    return {
        "change_id": str(uuid.uuid4()),
        "structure_id": structure_id,
        "source_run_id": source_run_id,
        "change_type": change_type,
        "changed_fields": fields,
        "before_payload": json_safe(canonical_row),
        "after_payload": json_safe(raw_payload),
        "detected_at": utc_now_iso(),
        "data_refresh_timestamp": (raw_row or {}).get("data_refresh_timestamp"),
    }


# Compare staged rows to canonical records and write change-log rows.
def detect_structure_changes(
    source_run_id: str,
    config: PipelineConfig,
    *,
    store: InMemoryRefreshStore,
) -> dict:
    """Compare staged rows to canonical records and write change-log rows."""
    raw_rows = store.raw_rows_for_run(source_run_id)
    canonical_rows = store.canonical_rows()
    source_runs = getattr(store, "source_runs", {})
    source_run = source_runs.get(source_run_id, {}) if isinstance(source_runs, dict) else {}
    data_refresh_timestamp = config.data_refresh_timestamp or source_run.get("data_refresh_timestamp")
    matched_ids: set[str] = set()
    changes: list[dict] = []
    for raw_row in raw_rows:
        canonical_row = match_canonical_row(raw_row, canonical_rows)
        if canonical_row is None:
            changes.append(build_change_row(source_run_id, "insert", raw_row, None))
            continue
        matched_ids.add(str(canonical_row.get("StructureID")))
        fields = changed_fields(raw_row["raw_payload"], canonical_row)
        changes.append(build_change_row(source_run_id, "update" if fields else "unchanged", raw_row, canonical_row))
    raw_city_state = {(row["city"], row["state"]) for row in raw_rows}
    for canonical_row in canonical_rows:
        if str(canonical_row.get("StructureID")) in matched_ids:
            continue
        if (str(canonical_row.get("City")), str(canonical_row.get("State"))) in raw_city_state:
            changes.append(build_change_row(source_run_id, "delete_candidate", None, canonical_row))
    for change in changes:
        if not change.get("data_refresh_timestamp"):
            change["data_refresh_timestamp"] = data_refresh_timestamp
    if not config.dry_run:
        store.insert_change_rows(changes)
    return {"source_run_id": source_run_id, "changes": changes}


# Convert approved change rows into canonical structure records.
def canonical_rows_from_changes(changes: list[dict], config: PipelineConfig) -> list[dict]:
    """Convert approved change rows into canonical structure records."""
    now = utc_now_iso()
    rows: list[dict] = []
    for change in changes:
        if change["change_type"] not in {"insert", "update"}:
            continue
        payload = deepcopy(change["after_payload"])
        payload["StructureID"] = canonical_structure_id(payload, change["structure_id"])
        payload["updated_at"] = now
        payload.setdefault("created_at", now)
        payload["updated_by"] = config.updated_by
        data_refresh_timestamp = config.data_refresh_timestamp or change.get("data_refresh_timestamp") or now
        payload["data_refresh_timestamp"] = data_refresh_timestamp
        payload["last_refreshed"] = config.refresh_metadata.get("last_refreshed") or data_refresh_timestamp
        payload["source_as_of"] = config.refresh_source_as_of or config.refresh_metadata.get("source_as_of") or config.source_version
        log = payload.get("change_log")
        if not isinstance(log, list):
            log = []
        log.append(
            {
                "source_run_id": change["source_run_id"],
                "change_type": change["change_type"],
                "changed_fields": change["changed_fields"],
                "detected_at": change["detected_at"],
                "data_refresh_timestamp": data_refresh_timestamp,
            }
        )
        payload["change_log"] = json.dumps(log, sort_keys=True)
        rows.append(payload)
    return rows


# Validate canonical promotion rows and return failed rows without mutating canonical state.
def qa_valid_canonical_rows(rows: list[dict]) -> tuple[gpd.GeoDataFrame, list[dict]]:
    """Validate canonical promotion rows and return failed rows without mutating canonical state."""
    valid_payloads: list[dict] = []
    failed: list[dict] = []
    for row in rows:
        try:
            geometry = wkt.loads(row.get("geometry_wkt") or "")
            payload = {key: value for key, value in row.items() if key != "geometry_wkt"}
            gdf = gpd.GeoDataFrame([payload], geometry=[geometry], crs="EPSG:4326")
            validate_output(gdf)
            valid_payloads.append(row)
        except Exception as exc:
            failed.append({"StructureID": row.get("StructureID"), "reason": str(exc), "row": json_safe(row)})
    if not valid_payloads:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), failed
    geometries = [wkt.loads(row["geometry_wkt"]) for row in valid_payloads]
    payloads = [{key: value for key, value in row.items() if key != "geometry_wkt"} for row in valid_payloads]
    batch = gpd.GeoDataFrame(payloads, geometry=geometries, crs="EPSG:4326")
    try:
        validate_output(batch)
    except Exception as exc:
        failed.extend(
            {"StructureID": row.get("StructureID"), "reason": str(exc), "row": json_safe(row)}
            for row in valid_payloads
        )
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), failed
    return batch, failed


# Promote valid insert/update changes into the canonical structure store.
def promote_valid_changes(
    source_run_id: str,
    config: PipelineConfig,
    *,
    store: InMemoryRefreshStore,
) -> dict:
    """Promote valid insert/update changes into the canonical structure store."""
    changes = store.changes_for_run(source_run_id)
    candidate_rows = canonical_rows_from_changes(changes, config)
    valid_gdf, failed_rows = qa_valid_canonical_rows(candidate_rows)
    promoted_rows = []
    if not valid_gdf.empty:
        promoted_rows = valid_gdf.drop(columns=["geometry"]).to_dict("records")
        geometry_wkt = valid_gdf.geometry.to_wkt().tolist()
        for index, row in enumerate(promoted_rows):
            row["geometry_wkt"] = geometry_wkt[index]
    if config.promote_to_canonical and not config.dry_run and promoted_rows:
        store.upsert_canonical_rows(promoted_rows)
        registry = build_gap_registry(valid_gdf, config)
        registry["data_refresh_timestamp"] = config.data_refresh_timestamp or utc_now_iso()
        store.upsert_coverage_rows(registry.to_dict("records"))
    if failed_rows and not config.dry_run:
        store.insert_promotion_failures(
            {
                "failure_id": str(uuid.uuid4()),
                "source_run_id": source_run_id,
                "structure_id": row.get("StructureID"),
                "reason": row["reason"],
                "failed_payload": row["row"],
                "detected_at": utc_now_iso(),
                "data_refresh_timestamp": config.data_refresh_timestamp or utc_now_iso(),
            }
            for row in failed_rows
        )
    return {
        "source_run_id": source_run_id,
        "promoted_rows": promoted_rows,
        "failed_rows": failed_rows,
        "promoted_count": len(promoted_rows),
        "failed_count": len(failed_rows),
    }


# Run staging, change detection, promotion, coverage, and release metadata as one cycle.
def run_refresh_cycle(
    source_name: str,
    city: str,
    state: str,
    config: PipelineConfig,
    *,
    source_frame: gpd.GeoDataFrame | None = None,
    store: InMemoryRefreshStore | None = None,
) -> dict:
    """Run staging, change detection, promotion, coverage, and release metadata as one cycle."""
    store = store or InMemoryRefreshStore()
    refresh = run_source_refresh(source_name, city, state, config, source_frame=source_frame, store=store)
    source_run_id = refresh["source_run"]["source_run_id"]
    config.data_refresh_timestamp = refresh["source_run"]["data_refresh_timestamp"]
    changes = detect_structure_changes(source_run_id, config, store=store)
    promotion = promote_valid_changes(source_run_id, config, store=store)
    source_run = refresh["source_run"]
    source_run["completed_at"] = utc_now_iso()
    source_run["status"] = "completed" if promotion["failed_count"] == 0 else "completed_with_failures"
    source_run["metadata"] = {
        **dict(source_run.get("metadata") or {}),
        "change_counts": pd.Series([row["change_type"] for row in changes["changes"]]).value_counts().to_dict(),
        "promoted_count": promotion["promoted_count"],
        "failed_count": promotion["failed_count"],
    }
    if not config.dry_run:
        store.upsert_source_run(source_run)
    canonical_gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    if promotion["promoted_rows"]:
        canonical_gdf = gpd.GeoDataFrame(
            [{key: value for key, value in row.items() if key != "geometry_wkt"} for row in promotion["promoted_rows"]],
            geometry=[wkt.loads(row["geometry_wkt"]) for row in promotion["promoted_rows"]],
            crs="EPSG:4326",
        )
    manifest = build_release_manifest(
        canonical_gdf,
        config,
        coverage_paths={},
        delivery_paths={},
        metrics=[source_run["metadata"]],
    )
    manifest["source_run"] = json_safe(source_run)
    manifest["refresh_status"] = source_run["status"]
    manifest["data_refresh_timestamp"] = source_run["data_refresh_timestamp"]
    if not config.dry_run:
        store.upsert_release_manifest(manifest)
    return {
        "source_run": source_run,
        "raw_rows": refresh["raw_rows"],
        "changes": changes["changes"],
        "promotion": promotion,
        "release_manifest": manifest,
        "store": store,
    }
