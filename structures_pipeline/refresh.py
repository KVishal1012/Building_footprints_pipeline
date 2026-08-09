from __future__ import annotations

import json
import os
import hashlib
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Iterable

import geopandas as gpd
import pandas as pd
import requests
import shapely
from shapely import wkt

from structures_pipeline.config import PipelineConfig
from structures_pipeline.constants import REQUIRED_OUTPUT_COLUMNS
from structures_pipeline.coverage import build_gap_registry
from structures_pipeline.foundation import (
    build_observation_rows,
    build_source_object_row,
    compact_field_deltas,
    observation_to_canonical,
    stable_checksum,
)
from structures_pipeline.passport import ai_suggestion_rows_from_canonical
from structures_pipeline.release import build_release_manifest
from structures_pipeline.utils import json_safe, utc_now_iso
from structures_pipeline.validation import validate_output

CHANGE_TYPES = {"insert", "update", "delete_candidate", "unchanged"}
RAW_REQUIRED_FIELDS = [
    "raw_record_id",
    "source_run_id",
    "source_object_id",
    "structure_id",
    "record_checksum",
    "raw_data_source",
    "source_authority",
    "source_family",
    "source_as_of",
    "city",
    "state",
    "geometry_wkt",
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
    "SourceAuthority": "source_authority",
    "SourceFamily": "source_family",
    "ProvenanceTier": "provenance_tier",
    "source_run_id": "source_run_id",
    "record_checksum": "record_checksum",
    "qa_status": "qa_status",
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
    source_objects: dict[str, dict] = field(default_factory=dict)
    raw_structures: list[dict] = field(default_factory=list)
    change_log: list[dict] = field(default_factory=list)
    promotion_failures: list[dict] = field(default_factory=list)
    canonical_structures: dict[str, dict] = field(default_factory=dict)
    coverage_registry: dict[tuple[str, str], dict] = field(default_factory=dict)
    release_manifests: dict[str, dict] = field(default_factory=dict)

    def upsert_source_object(self, row: dict) -> None:
        """Persist one immutable source-object reference for local workflow tests."""
        self.source_objects[row["source_object_id"]] = deepcopy(row)

    # Persist or replace one source run metadata row.
    def upsert_source_run(self, row: dict) -> None:
        """Persist or replace one source run metadata row."""
        self.source_runs[row["source_run_id"]] = deepcopy(row)

    # Append staged raw rows for a source run.
    def insert_raw_rows(self, rows: Iterable[dict]) -> None:
        """Append staged raw rows for a source run."""
        self.raw_structures.extend(list(rows))

    # Return raw rows staged for one source run.
    def raw_rows_for_run(self, source_run_id: str) -> list[dict]:
        """Return raw rows staged for one source run."""
        return [row for row in self.raw_structures if row["source_run_id"] == source_run_id]

    # Append change detector results.
    def insert_change_rows(self, rows: Iterable[dict]) -> None:
        """Append change detector results."""
        self.change_log.extend(list(rows))

    # Return detected change rows for one source run.
    def changes_for_run(self, source_run_id: str) -> list[dict]:
        """Return detected change rows for one source run."""
        return [row for row in self.change_log if row["source_run_id"] == source_run_id]

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
    def canonical_rows(
        self,
        *,
        city: str | None = None,
        state: str | None = None,
        raw_data_source: str | None = None,
    ) -> list[dict]:
        """Return canonical records as dictionaries."""
        rows = list(self.canonical_structures.values())
        if city is not None:
            rows = [row for row in rows if str(row.get("City")) == city]
        if state is not None:
            rows = [row for row in rows if str(row.get("State")) == state]
        if raw_data_source is not None:
            rows = [row for row in rows if str(row.get("RawDataSource")) == raw_data_source]
        return rows

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

    _PAGE_KEYS = {
        "source_objects_table": ("source_object_id",),
        "source_runs_table": ("source_run_id",),
        "raw_table": ("raw_record_id",),
        "change_log_table": ("change_id",),
        "promotion_failures_table": ("failure_id",),
        "promotion_batches_table": ("source_run_id", "batch_number"),
        "canonical_table": ("structure_id",),
        "coverage_table": ("city", "state"),
        "release_table": ("release_id",),
    }

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
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Modern Supabase secret keys authenticate through the apikey header and
        # are not JWTs. Legacy service_role keys remain valid Bearer tokens.
        if not self.service_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.service_key}"
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
        response = None
        for attempt in range(int(self.config.supabase_max_retries) + 1):
            try:
                response = self.session.request(
                    method,
                    f"{self.supabase_url}/rest/v1/{table}",
                    headers=headers,
                    params=request_params,
                    json=_json_ready(payload) if payload is not None else None,
                    timeout=int(self.config.request_timeout_sec),
                )
            except requests.RequestException:
                if attempt >= int(self.config.supabase_max_retries):
                    raise
                time.sleep(float(self.config.supabase_retry_backoff_sec) * (2**attempt))
                continue
            if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
                break
            if attempt >= int(self.config.supabase_max_retries):
                break
            time.sleep(float(self.config.supabase_retry_backoff_sec) * (2**attempt))
        if response is None or response.status_code >= 400:
            status = response.status_code if response is not None else "no_response"
            detail = response.text if response is not None else ""
            raise RuntimeError(f"Supabase {method} {schema}.{table} failed: {status} {detail}")
        if not response.text:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def _rpc(self, function_name: str, payload: dict, *, schema: str = "public"):
        """Call one schema-scoped PostgREST RPC with service-role credentials."""
        headers = self._headers(schema, write=True)
        response = self.session.request(
            "POST",
            f"{self.supabase_url}/rest/v1/rpc/{function_name}",
            headers={**headers, "Prefer": "return=representation"},
            json=_json_ready(payload),
            timeout=int(self.config.request_timeout_sec),
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Supabase RPC {schema}.{function_name} failed: "
                f"{response.status_code} {response.text}"
            )
        if not response.text:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def _write_batches(
        self,
        config_key: str,
        rows: Iterable[dict],
        *,
        upsert_key: str | None = None,
    ) -> None:
        """Write bounded payloads so large city refreshes do not exceed API limits."""
        batch_size = max(1, int(self.config.supabase_batch_size))
        batch: list[dict] = []
        for row in rows:
            batch.append(row)
            if len(batch) >= batch_size:
                self._request("POST", config_key, payload=batch, upsert_key=upsert_key)
                batch = []
        if batch:
            self._request("POST", config_key, payload=batch, upsert_key=upsert_key)

    def _paged_get(self, config_key: str, *, params: dict | None = None) -> list[dict]:
        """Read all PostgREST pages in stable key order, using a cursor when possible."""
        page_size = max(1, int(self.config.supabase_page_size))
        offset = 0
        cursor: str | None = None
        rows: list[dict] = []
        page_keys = self._PAGE_KEYS[config_key]
        order = ",".join(f"{key}.asc" for key in page_keys)
        while True:
            page_params = {
                **dict(params or {}),
                "order": order,
                "limit": page_size,
            }
            if len(page_keys) == 1 and cursor is not None:
                page_params[page_keys[0]] = f"gt.{cursor}"
            elif len(page_keys) > 1:
                page_params["offset"] = offset
            page = self._request("GET", config_key, params=page_params) or []
            rows.extend(page)
            if len(page) < page_size:
                return rows
            if len(page_keys) == 1:
                next_cursor = _present_text(page[-1].get(page_keys[0]))
                if next_cursor is None or next_cursor == cursor:
                    raise RuntimeError(
                        f"Supabase pagination did not advance for {config_key}"
                    )
                cursor = next_cursor
            else:
                offset += page_size

    def preflight(self) -> dict:
        """Verify every required PostgREST table is reachable before mutating a run."""
        checked = []
        for config_key in (
            "source_objects_table",
            "source_runs_table",
            "raw_table",
            "change_log_table",
            "promotion_failures_table",
            "promotion_batches_table",
            "canonical_table",
            "coverage_table",
            "release_table",
            "conflicts_table",
            "quality_issues_table",
            "relationships_table",
            "ai_suggestions_table",
        ):
            self._request("GET", config_key, params={"select": "*", "limit": 1})
            checked.append(self.config.canonical_database[config_key])
        return {"status": "passed", "tables": checked}

    def upsert_source_object(self, row: dict) -> None:
        """Register a checksummed immutable source object before row staging."""
        row = deepcopy(row)
        if self.config.refresh_require_archive and self.config.refresh_verify_archive:
            self._verify_source_object(row)
        self._request(
            "POST",
            "source_objects_table",
            payload=row,
            upsert_key="source_object_id",
        )

    def _verify_source_object(self, row: dict) -> None:
        """Stream a private Storage object and reject missing or altered archives."""
        bucket = row["bucket_id"]
        object_path = str(row["object_path"]).lstrip("/")
        headers = {
            "apikey": self.service_key,
            "Accept": "application/octet-stream",
        }
        if not self.service_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.service_key}"
        response = self.session.request(
            "GET",
            f"{self.supabase_url}/storage/v1/object/authenticated/{bucket}/{object_path}",
            headers=headers,
            stream=True,
            timeout=int(self.config.request_timeout_sec),
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Supabase source archive verification failed: "
                f"{response.status_code} {response.text}"
            )
        digest = hashlib.sha256()
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                digest.update(chunk)
        if digest.hexdigest() != row["checksum_sha256"]:
            raise ValueError("Supabase source archive checksum does not match local source")
        row["archive_status"] = "verified"
        row["verified_at"] = utc_now_iso()

    # Persist or replace one source run metadata row.
    def upsert_source_run(self, row: dict) -> None:
        """Persist or replace one source run metadata row."""
        self._request("POST", "source_runs_table", payload=row, upsert_key="source_run_id")

    # Append staged raw rows for a source run.
    def insert_raw_rows(self, rows: Iterable[dict]) -> None:
        """Stage normalized rows through an RPC that converts transient WKT to PostGIS."""
        batch_size = max(1, int(self.config.supabase_batch_size))
        batch: list[dict] = []
        for row in rows:
            batch.append(row)
            if len(batch) >= batch_size:
                self._rpc("stage_structure_observations", {"p_rows": batch}, schema="staging")
                batch = []
        if batch:
            self._rpc("stage_structure_observations", {"p_rows": batch}, schema="staging")

    # Return raw rows staged for one source run.
    def raw_rows_for_run(self, source_run_id: str) -> list[dict]:
        """Return raw rows staged for one source run."""
        return self._paged_get("raw_table", params={"source_run_id": f"eq.{source_run_id}"})

    # Append change detector results.
    def insert_change_rows(self, rows: Iterable[dict]) -> None:
        """Append change detector results."""
        self._write_batches("change_log_table", rows, upsert_key="change_id")

    # Return detected change rows for one source run.
    def changes_for_run(self, source_run_id: str) -> list[dict]:
        """Return detected change rows for one source run."""
        return self._paged_get("change_log_table", params={"source_run_id": f"eq.{source_run_id}"})

    # Append rows blocked by promotion QA.
    def insert_promotion_failures(self, rows: Iterable[dict]) -> None:
        """Append rows blocked by promotion QA."""
        self._write_batches("promotion_failures_table", rows, upsert_key="failure_id")

    # Upsert approved canonical records.
    def upsert_canonical_rows(self, rows: Iterable[dict]) -> None:
        """Upsert approved canonical records."""
        self._write_batches(
            "canonical_table",
            (canonical_row_to_db(row) for row in rows),
            upsert_key="structure_id",
        )

    # Return canonical records as dictionaries.
    def canonical_rows(
        self,
        *,
        city: str | None = None,
        state: str | None = None,
        raw_data_source: str | None = None,
    ) -> list[dict]:
        """Return canonical records as dictionaries."""
        params = {}
        if city is not None:
            params["city"] = f"eq.{city}"
        if state is not None:
            params["state"] = f"eq.{state}"
        if raw_data_source is not None:
            params["raw_data_source"] = f"eq.{raw_data_source}"
        rows = self._paged_get("canonical_table", params=params)
        return [canonical_row_from_db(row) for row in rows]

    # Store coverage registry rows keyed by city/state.
    def upsert_coverage_rows(self, rows: Iterable[dict]) -> None:
        """Store coverage registry rows keyed by city/state."""
        self._write_batches(
            "coverage_table",
            (coverage_row_to_db(row) for row in rows),
            upsert_key="city,state",
        )

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

    def promote_canonical_batches(self, source_run_id: str, rows: Iterable[dict]) -> int:
        """Promote canonical rows in bounded, idempotent database transactions."""
        batch_size = max(1, int(self.config.promotion_batch_size))
        promoted = 0
        batch: list[dict] = []
        batch_number = 0
        for row in rows:
            batch.append(canonical_row_to_db(row))
            if len(batch) >= batch_size:
                promoted += self._promote_batch(source_run_id, batch_number, batch)
                batch_number += 1
                batch = []
        if batch:
            promoted += self._promote_batch(source_run_id, batch_number, batch)
        return promoted

    def _promote_batch(self, source_run_id: str, batch_number: int, batch: list[dict]) -> int:
        """Call the transactional promotion RPC for one deterministic payload batch."""
        batch_hash = stable_checksum({"source_run_id": source_run_id, "rows": batch})
        result = self._rpc(
            "promote_structure_batch_v3",
            {
                "p_source_run_id": source_run_id,
                "p_batch_number": batch_number,
                "p_batch_hash": batch_hash,
                "p_rows": batch,
            },
        )
        if isinstance(result, int):
            return result
        return len(batch)

    def upsert_ai_suggestions(self, rows: Iterable[dict]) -> None:
        """Persist suggest-only model output outside the canonical structure row."""
        self._write_batches("ai_suggestions_table", rows)

    def finalize_refresh(
        self,
        source_run_id: str,
        coverage_rows: list[dict],
        manifest: dict,
        *,
        expected_promoted_count: int = 0,
    ) -> None:
        """Finalize metadata only after all bounded promotion batches complete."""
        manifest = deepcopy(manifest)
        manifest["promotion_contract"] = {
            "mode": "bounded_transactional_batches",
            "expected_promoted_count": expected_promoted_count,
        }
        self._rpc(
            "finalize_structure_refresh_v3",
            {
                "p_source_run_id": source_run_id,
                "p_expected_promoted_count": expected_promoted_count,
                "p_coverage_rows": [
                    coverage_row_to_db(row) for row in coverage_rows
                ],
                "p_release_manifest": {
                    "release_id": manifest["release_id"],
                    "generated_at": manifest.get("generated_at"),
                    "schema_version": manifest.get("schema_version", "3.0"),
                    "row_count": int(manifest.get("row_count") or 0),
                    "manifest": manifest,
                },
            },
        )

    def structure_passport(self, structure_id: str) -> dict | None:
        """Fetch the database-built Structure Passport for one canonical structure."""
        return self._rpc("get_structure_passport", {"p_structure_id": structure_id})


# Convert a canonical pipeline row into the public.structures database shape.
def canonical_row_to_db(row: dict) -> dict:
    """Convert a canonical pipeline row into the public.structures database shape."""
    db_row = {db_key: _json_ready(row.get(source_key)) for source_key, db_key in CANONICAL_TO_DB_COLUMNS.items()}
    if isinstance(db_row.get("change_log"), str):
        try:
            db_row["change_log"] = json.loads(db_row["change_log"])
        except json.JSONDecodeError:
            db_row["change_log"] = []
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
    # Kept only for legacy schema compatibility. AI output is stored in the
    # dedicated suggestions table and never inside the canonical record.
    db_row["ai_suggestions"] = {}
    return db_row


# Convert a public.structures database row back into the canonical pipeline shape.
def canonical_row_from_db(row: dict) -> dict:
    """Convert a public.structures database row back into the canonical pipeline shape."""
    converted = {canonical_key: row.get(db_key) for db_key, canonical_key in DB_TO_CANONICAL_COLUMNS.items()}
    if converted.get("geometry_wkt") is None and isinstance(row.get("geom"), dict):
        from shapely.geometry import shape

        converted["geometry_wkt"] = shape(row["geom"]).wkt
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
        "source_run_id": source_run_id or config.refresh_source_run_id or make_source_run_id(source_name, city, state, started_at),
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
        "city": city,
        "state": state,
        "source_object_id": config.refresh_source_object_id,
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
    """Convert source rows into normalized observations without copying raw payloads."""
    source_object = build_source_object_row(config, source_run)
    source_run["source_object_id"] = source_object["source_object_id"]
    return build_observation_rows(source_frame, source_run, source_object, config)


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
    if config.refresh_require_nonempty and source_frame.empty:
        raise ValueError("Source refresh input is empty")
    source_run = build_source_run_row(source_name, city, state, config, row_count=len(source_frame))
    source_object = build_source_object_row(config, source_run)
    source_run["source_object_id"] = source_object["source_object_id"]
    raw_rows = build_raw_structure_rows(source_frame, source_run, config)
    validate_raw_rows(raw_rows)
    if not config.dry_run:
        store.upsert_source_object(source_object)
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
    payload = observation_to_canonical(raw_row)
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
    return list(compact_field_deltas(raw_payload, canonical_row))


# Build one staging.change_log row.
def build_change_row(source_run_id: str, change_type: str, raw_row: dict | None, canonical_row: dict | None) -> dict:
    """Build one staging.change_log row."""
    if change_type not in CHANGE_TYPES:
        raise ValueError(f"Unsupported change type: {change_type}")
    raw_payload = observation_to_canonical(raw_row) if raw_row else {}
    structure_id = canonical_structure_id(raw_payload, "") or (canonical_row or {}).get("StructureID")
    deltas = compact_field_deltas(raw_payload, canonical_row) if raw_row else {}
    if change_type == "insert":
        deltas = {
            field: {"before": None, "after": raw_payload.get(field)}
            for field in ("StructureID", "geometry_wkt", "RawDataSource")
        }
    return {
        "change_id": str(uuid.uuid4()),
        "structure_id": structure_id,
        "source_run_id": source_run_id,
        "change_type": change_type,
        "raw_record_id": (raw_row or {}).get("raw_record_id"),
        "city": (raw_row or {}).get("city") or (canonical_row or {}).get("City"),
        "state": (raw_row or {}).get("state") or (canonical_row or {}).get("State"),
        "changed_fields": list(deltas),
        "field_deltas": json_safe(deltas),
        "before_checksum": (canonical_row or {}).get("record_checksum"),
        "after_checksum": (raw_row or {}).get("record_checksum"),
        "geometry_changed": "geometry_wkt" in deltas,
        "detected_at": utc_now_iso(),
        "data_refresh_timestamp": (raw_row or {}).get("data_refresh_timestamp"),
    }


# Compare staged rows to canonical records and write change-log rows.
def detect_structure_changes(
    source_run_id: str,
    config: PipelineConfig,
    *,
    store: InMemoryRefreshStore,
    raw_rows: list[dict] | None = None,
) -> dict:
    """Compare staged rows to canonical records and write change-log rows."""
    raw_rows = raw_rows if raw_rows is not None else store.raw_rows_for_run(source_run_id)
    raw_source_names = {str(row.get("raw_data_source")) for row in raw_rows}
    canonical_rows = store.canonical_rows(city=config.refresh_city, state=config.refresh_state)
    source_runs = getattr(store, "source_runs", {})
    source_run = source_runs.get(source_run_id, {}) if isinstance(source_runs, dict) else {}
    data_refresh_timestamp = config.data_refresh_timestamp or source_run.get("data_refresh_timestamp")
    matched_ids: set[str] = set()
    changes: list[dict] = []
    canonical_by_id: dict[str, dict] = {}
    for canonical_row in canonical_rows:
        for key in ("StructureID", "structure_id", "OvertureID", "overture_id"):
            value = _present_text(canonical_row.get(key))
            if value is not None:
                canonical_by_id.setdefault(value, canonical_row)
    for raw_row in raw_rows:
        payload = observation_to_canonical(raw_row)
        canonical_row = next(
            (
                canonical_by_id[value]
                for value in (
                    _present_text(payload.get("StructureID")),
                    _present_text(payload.get("structure_id")),
                    _present_text(payload.get("OvertureID")),
                    _present_text(payload.get("overture_id")),
                    _present_text(raw_row.get("raw_record_id")),
                )
                if value is not None and value in canonical_by_id
            ),
            None,
        )
        if canonical_row is None and canonical_rows:
            canonical_row = match_canonical_row(raw_row, canonical_rows)
        if canonical_row is None:
            changes.append(build_change_row(source_run_id, "insert", raw_row, None))
            continue
        matched_ids.add(str(canonical_row.get("StructureID")))
        fields = changed_fields(payload, canonical_row)
        changes.append(build_change_row(source_run_id, "update" if fields else "unchanged", raw_row, canonical_row))
    raw_city_state = {(row["city"], row["state"]) for row in raw_rows}
    for canonical_row in canonical_rows:
        if str(canonical_row.get("StructureID")) in matched_ids:
            continue
        same_source = str(canonical_row.get("RawDataSource")) in raw_source_names
        if same_source and (str(canonical_row.get("City")), str(canonical_row.get("State"))) in raw_city_state:
            changes.append(build_change_row(source_run_id, "delete_candidate", None, canonical_row))
    for change in changes:
        if not change.get("data_refresh_timestamp"):
            change["data_refresh_timestamp"] = data_refresh_timestamp
    if not config.dry_run:
        store.insert_change_rows(changes)
    return {"source_run_id": source_run_id, "changes": changes}


# Convert approved change rows into canonical structure records.
def canonical_rows_from_changes(
    changes: list[dict],
    config: PipelineConfig,
    observations: list[dict] | None = None,
) -> list[dict]:
    """Convert approved change rows into canonical structure records."""
    now = utc_now_iso()
    rows: list[dict] = []
    observation_by_record = {
        row.get("raw_record_id"): row for row in (observations or [])
    }
    for change in changes:
        if change["change_type"] not in {"insert", "update"}:
            continue
        observation = observation_by_record.get(change.get("raw_record_id"))
        if observation is None:
            raise ValueError(
                "Canonical promotion requires normalized observations; "
                f"missing {change.get('raw_record_id')}"
            )
        payload = observation_to_canonical(observation)
        payload["StructureID"] = canonical_structure_id(payload, change["structure_id"])
        payload["updated_at"] = now
        payload.setdefault("created_at", now)
        payload["updated_by"] = config.updated_by
        data_refresh_timestamp = config.data_refresh_timestamp or change.get("data_refresh_timestamp") or now
        payload["data_refresh_timestamp"] = data_refresh_timestamp
        payload["last_refreshed"] = config.refresh_metadata.get("last_refreshed") or data_refresh_timestamp
        payload["source_as_of"] = config.refresh_source_as_of or config.refresh_metadata.get("source_as_of") or config.source_version
        payload["source_run_id"] = change["source_run_id"]
        payload["record_checksum"] = observation.get("record_checksum")
        payload["qa_status"] = "passed"
        payload["SourceAuthority"] = payload.get("SourceAuthority") or config.refresh_metadata.get("source_authority")
        payload["SourceFamily"] = payload.get("SourceFamily") or config.refresh_source_family
        payload["ProvenanceTier"] = payload.get("ProvenanceTier") or config.refresh_metadata.get("provenance_tier")
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
        payload["change_log"] = log
        for column in REQUIRED_OUTPUT_COLUMNS:
            if column != "geometry":
                payload.setdefault(column, pd.NA)
        rows.append(payload)
    return rows


# Validate canonical promotion rows and return failed rows without mutating canonical state.
def qa_valid_canonical_rows(rows: list[dict]) -> tuple[gpd.GeoDataFrame, list[dict]]:
    """Validate canonical promotion rows and return failed rows without mutating canonical state."""
    if not rows:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), []
    geometry_text = [row.get("geometry_wkt") or "" for row in rows]
    geometries = shapely.from_wkt(geometry_text, on_invalid="ignore")
    payloads = [{key: value for key, value in row.items() if key != "geometry_wkt"} for row in rows]
    batch = gpd.GeoDataFrame(payloads, geometry=geometries, crs="EPSG:4326")
    duplicate_mask = batch["StructureID"].duplicated(keep=False)
    if duplicate_mask.any():
        duplicate_count = int(duplicate_mask.sum())
        failed = [
            {
                "StructureID": rows[index].get("StructureID"),
                "reason": f"Output contains a duplicated StructureID ({duplicate_count} affected rows)",
                "row": json_safe(rows[index]),
            }
            for index in duplicate_mask[duplicate_mask].index
        ]
        batch = batch.loc[~duplicate_mask].reset_index(drop=True)
        rows = [row for index, row in enumerate(rows) if not duplicate_mask.iloc[index]]
        if batch.empty:
            return batch, failed
    else:
        failed = []
    try:
        validate_output(batch)
    except Exception as exc:
        valid_indexes: list[int] = []
        for index, row in enumerate(rows):
            try:
                single = batch.iloc[[index]]
                validate_output(single)
                valid_indexes.append(index)
            except Exception as row_exc:
                failed.append(
                    {
                        "StructureID": row.get("StructureID"),
                        "reason": str(row_exc),
                        "row": json_safe(row),
                    }
                )
        if not valid_indexes:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), failed
        valid = batch.iloc[valid_indexes].reset_index(drop=True)
        try:
            validate_output(valid)
        except Exception:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), [
                {
                    "StructureID": row.get("StructureID"),
                    "reason": str(exc),
                    "row": json_safe(row),
                }
                for row in rows
            ]
        return valid, failed
    return batch, failed


# Promote valid insert/update changes into the canonical structure store.
def promote_valid_changes(
    source_run_id: str,
    config: PipelineConfig,
    *,
    store: InMemoryRefreshStore,
    observations: list[dict] | None = None,
    changes: list[dict] | None = None,
) -> dict:
    """Promote valid insert/update changes into the canonical structure store."""
    changes = changes if changes is not None else store.changes_for_run(source_run_id)
    observations = observations if observations is not None else store.raw_rows_for_run(source_run_id)
    candidate_rows = canonical_rows_from_changes(changes, config, observations)
    valid_gdf, failed_rows = qa_valid_canonical_rows(candidate_rows)
    promoted_rows = []
    if not valid_gdf.empty:
        promoted_rows = valid_gdf.drop(columns=["geometry"]).to_dict("records")
        geometry_wkt = valid_gdf.geometry.to_wkt(rounding_precision=-1).tolist()
        for index, row in enumerate(promoted_rows):
            row["geometry_wkt"] = geometry_wkt[index]
    if config.promote_to_canonical and not config.dry_run and promoted_rows:
        if isinstance(store, SupabaseRefreshStore):
            store.promote_canonical_batches(source_run_id, promoted_rows)
            suggestions = [
                suggestion
                for row in promoted_rows
                for suggestion in ai_suggestion_rows_from_canonical(row)
            ]
            if suggestions:
                store.upsert_ai_suggestions(suggestions)
        else:
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
                "source_record_id": row.get("raw_record_id"),
                "reason": row["reason"],
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
    resume_staged: bool = False,
) -> dict:
    """Run staging, change detection, promotion, coverage, and release metadata as one cycle."""
    store = store or InMemoryRefreshStore()
    if resume_staged:
        if not config.refresh_source_run_id:
            raise ValueError("Resuming a staged refresh requires config.refresh_source_run_id")
        staged_rows = store.raw_rows_for_run(config.refresh_source_run_id)
        if not staged_rows:
            raise ValueError(f"No staged raw rows found for {config.refresh_source_run_id}")
        source_run = build_source_run_row(source_name, city, state, config, row_count=len(staged_rows))
        source_run["metadata"] = {
            **dict(source_run.get("metadata") or {}),
            "resumed_from_staging": True,
        }
        if not config.dry_run:
            store.upsert_source_run(source_run)
        refresh = {"source_run": source_run, "raw_rows": staged_rows, "store": store}
    else:
        refresh = run_source_refresh(source_name, city, state, config, source_frame=source_frame, store=store)
    source_run_id = refresh["source_run"]["source_run_id"]
    config.data_refresh_timestamp = refresh["source_run"]["data_refresh_timestamp"]
    working_store = store
    if config.dry_run:
        existing = store.canonical_rows(city=city, state=state)
        working_store = InMemoryRefreshStore(
            canonical_structures={
                str(row["StructureID"]): row
                for row in existing
                if row.get("StructureID") is not None
            }
        )
        working_store.upsert_source_run(refresh["source_run"])
        working_store.insert_raw_rows(refresh["raw_rows"])
    existing_changes = working_store.changes_for_run(source_run_id) if resume_staged else []
    if existing_changes:
        changes = {"source_run_id": source_run_id, "changes": existing_changes}
    else:
        changes = detect_structure_changes(
            source_run_id,
            config,
            store=working_store,
            raw_rows=refresh["raw_rows"] if resume_staged else None,
        )
    if config.dry_run:
        working_store.insert_change_rows(changes["changes"])
    promotion = promote_valid_changes(
        source_run_id,
        config,
        store=working_store,
        observations=refresh["raw_rows"],
        changes=changes["changes"],
    )
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
        if isinstance(store, SupabaseRefreshStore) and config.promote_to_canonical:
            coverage = build_gap_registry(canonical_gdf, config)
            coverage["data_refresh_timestamp"] = config.data_refresh_timestamp or utc_now_iso()
            store.finalize_refresh(
                source_run_id,
                coverage.to_dict("records"),
                manifest,
                expected_promoted_count=promotion["promoted_count"],
            )
        else:
            store.upsert_release_manifest(manifest)
    raw_result = refresh["raw_rows"]
    change_result = changes["changes"]
    promoted_result = promotion
    if config.refresh_compact_results:
        raw_result = []
        change_result = []
        promoted_result = {
            **promotion,
            "promoted_rows": [],
            "failed_rows": [],
        }
        if isinstance(working_store, InMemoryRefreshStore):
            working_store.raw_structures.clear()
            working_store.change_log.clear()
    return {
        "source_run": source_run,
        "raw_rows": raw_result,
        "changes": change_result,
        "promotion": promoted_result,
        "release_manifest": manifest,
        "store": store,
    }
