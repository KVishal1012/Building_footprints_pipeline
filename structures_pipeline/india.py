from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from structures_pipeline.config import PipelineConfig


@dataclass(frozen=True)
class IndiaCityRegistryEntry:
    """Describe one India city that can be handled by the refresh workflow."""

    slug: str
    city: str
    state: str
    state_code: str
    country: str
    coverage_tier: str
    status: str
    expansion_order: int
    default_source_name: str
    default_source_file: str
    known_gap: str


@dataclass(frozen=True)
class IndiaSourceRegistryEntry:
    """Describe one India source configuration used by refresh runs."""

    source_name: str
    source_family: str
    source_authority: str
    refresh_cadence: str
    source_as_of: str
    treatment: str
    notes: str


CHENNAI_SOURCE_FILE = "examples/india_chennai_refresh_source.csv"

TAMIL_NADU_CITY_REGISTRY: dict[str, IndiaCityRegistryEntry] = {
    "chennai": IndiaCityRegistryEntry(
        slug="chennai",
        city="Chennai",
        state="Tamil Nadu",
        state_code="TN",
        country="India",
        coverage_tier="Tier 4",
        status="active_proof_market",
        expansion_order=1,
        default_source_name="openstreetmap",
        default_source_file=CHENNAI_SOURCE_FILE,
        known_gap="Authoritative municipal building attributes are not yet onboarded.",
    ),
    "coimbatore": IndiaCityRegistryEntry(
        slug="coimbatore",
        city="Coimbatore",
        state="Tamil Nadu",
        state_code="TN",
        country="India",
        coverage_tier="Tier 4",
        status="planned_expansion",
        expansion_order=2,
        default_source_name="overture_osm_fallback",
        default_source_file="",
        known_gap="City fixture and authoritative source mapping are not yet prepared.",
    ),
    "madurai": IndiaCityRegistryEntry(
        slug="madurai",
        city="Madurai",
        state="Tamil Nadu",
        state_code="TN",
        country="India",
        coverage_tier="Tier 4",
        status="planned_expansion",
        expansion_order=3,
        default_source_name="overture_osm_fallback",
        default_source_file="",
        known_gap="City fixture and authoritative source mapping are not yet prepared.",
    ),
    "tiruchirappalli": IndiaCityRegistryEntry(
        slug="tiruchirappalli",
        city="Tiruchirappalli",
        state="Tamil Nadu",
        state_code="TN",
        country="India",
        coverage_tier="Tier 4",
        status="planned_expansion",
        expansion_order=4,
        default_source_name="overture_osm_fallback",
        default_source_file="",
        known_gap="City fixture and authoritative source mapping are not yet prepared.",
    ),
    "salem": IndiaCityRegistryEntry(
        slug="salem",
        city="Salem",
        state="Tamil Nadu",
        state_code="TN",
        country="India",
        coverage_tier="Tier 4",
        status="planned_expansion",
        expansion_order=5,
        default_source_name="overture_osm_fallback",
        default_source_file="",
        known_gap="City fixture and authoritative source mapping are not yet prepared.",
    ),
    "tiruppur": IndiaCityRegistryEntry(
        slug="tiruppur",
        city="Tiruppur",
        state="Tamil Nadu",
        state_code="TN",
        country="India",
        coverage_tier="Tier 4",
        status="planned_expansion",
        expansion_order=6,
        default_source_name="overture_osm_fallback",
        default_source_file="",
        known_gap="City fixture and authoritative source mapping are not yet prepared.",
    ),
}

INDIA_SOURCE_REGISTRY: dict[str, IndiaSourceRegistryEntry] = {
    "openstreetmap": IndiaSourceRegistryEntry(
        source_name="openstreetmap",
        source_family="open_community",
        source_authority="OpenStreetMap contributors",
        refresh_cadence="monthly_or_on_source_update",
        source_as_of="source_manifest",
        treatment="source_footprint_and_tag",
        notes="Real OSM building footprints clipped to the documented GCC ward boundary.",
    ),
    "chennai_overture_osm_fallback": IndiaSourceRegistryEntry(
        source_name="chennai_overture_osm_fallback",
        source_family="overture_osm_fallback",
        source_authority="Overture Maps / OpenStreetMap",
        refresh_cadence="monthly_or_on_source_update",
        source_as_of="2026-Q2",
        treatment="footprint_and_fallback",
        notes="Use as Chennai footprint/fallback data until authoritative municipal attributes are onboarded.",
    ),
    "overture_osm_fallback": IndiaSourceRegistryEntry(
        source_name="overture_osm_fallback",
        source_family="overture_osm_fallback",
        source_authority="Overture Maps / OpenStreetMap",
        refresh_cadence="monthly_or_on_source_update",
        source_as_of="latest",
        treatment="footprint_and_fallback",
        notes="Default fallback source for Tamil Nadu cities before city-specific source mapping is prepared.",
    ),
    "municipal_authoritative": IndiaSourceRegistryEntry(
        source_name="municipal_authoritative",
        source_family="authoritative_municipal",
        source_authority="Municipal or planning authority",
        refresh_cadence="quarterly_or_on_release",
        source_as_of="source_release",
        treatment="authoritative_when_acquired",
        notes="Use only after the source is acquired, documented, and mapped into canonical fields.",
    ),
    "state_reference": IndiaSourceRegistryEntry(
        source_name="state_reference",
        source_family="authoritative_state",
        source_authority="Tamil Nadu state reference dataset",
        refresh_cadence="quarterly_or_on_release",
        source_as_of="source_release",
        treatment="authoritative_when_acquired",
        notes="Use for state-level planning, disaster, parcel, or tax references when acquired and labeled.",
    ),
}


def get_tamil_nadu_city(slug_or_city: str) -> IndiaCityRegistryEntry:
    """Return a Tamil Nadu city registry entry by slug or display name."""
    normalized = slug_or_city.strip().lower().replace(" ", "_")
    for entry in TAMIL_NADU_CITY_REGISTRY.values():
        aliases = {entry.slug, entry.city.lower(), entry.city.lower().replace(" ", "_")}
        if normalized in aliases:
            return entry
    raise KeyError(f"Unsupported Tamil Nadu city: {slug_or_city}")


def get_india_source(source_name: str) -> IndiaSourceRegistryEntry:
    """Return a configured India source registry entry."""
    try:
        return INDIA_SOURCE_REGISTRY[source_name]
    except KeyError as exc:
        raise KeyError(f"Unsupported India source: {source_name}") from exc


def tamil_nadu_city_registry_rows() -> list[dict]:
    """Return city registry rows ordered by Tamil Nadu expansion sequence."""
    return [asdict(entry) for entry in sorted(TAMIL_NADU_CITY_REGISTRY.values(), key=lambda item: item.expansion_order)]


def india_source_registry_rows() -> list[dict]:
    """Return configured India source rows ordered by source name."""
    return [asdict(INDIA_SOURCE_REGISTRY[name]) for name in sorted(INDIA_SOURCE_REGISTRY)]


def build_india_refresh_config(
    *,
    city_slug: str = "chennai",
    source_name: str | None = None,
    source_as_of: str | None = None,
    source_run_id: str | None = None,
    data_refresh_timestamp: str | None = None,
    dry_run: bool = False,
    promote_to_canonical: bool = True,
    supabase_url: str | None = None,
    supabase_service_role_env: str = "SUPABASE_SERVICE_ROLE_KEY",
) -> PipelineConfig:
    """Build a PipelineConfig with India/Tamil Nadu refresh defaults."""
    city = get_tamil_nadu_city(city_slug)
    source = get_india_source(source_name or city.default_source_name)
    resolved_source_as_of = source_as_of or source.source_as_of
    return PipelineConfig(
        country=city.country,
        source_version=resolved_source_as_of,
        refresh_city=city.city,
        refresh_state=city.state,
        refresh_source_name=source.source_name,
        refresh_source_family=source.source_family,
        refresh_source_as_of=resolved_source_as_of,
        refresh_cadence=source.refresh_cadence,
        refresh_source_run_id=source_run_id,
        data_refresh_timestamp=data_refresh_timestamp,
        dry_run=dry_run,
        promote_to_canonical=promote_to_canonical,
        supabase_url=supabase_url,
        supabase_service_role_env=supabase_service_role_env,
        updated_by="india_structure_refresh",
        release_id=f"india-{city.slug}-{source.source_name}-{resolved_source_as_of}".lower().replace("_", "-"),
        refresh_metadata={
            "branch": "India_Structure_AI",
            "country": city.country,
            "city_slug": city.slug,
            "state_code": city.state_code,
            "coverage_tier": city.coverage_tier,
            "source_authority": source.source_authority,
            "provenance_tier": "open_community",
            "source_treatment": source.treatment,
            "known_gap": city.known_gap,
            "last_refreshed": data_refresh_timestamp,
            "source_as_of": resolved_source_as_of,
            "refresh_cadence": source.refresh_cadence,
        },
    )


def default_source_path(city_slug: str = "chennai") -> Path:
    """Return the default prepared source file path for a Tamil Nadu city."""
    city = get_tamil_nadu_city(city_slug)
    if not city.default_source_file:
        raise ValueError(f"No prepared source file is registered for {city.city}")
    return Path(city.default_source_file)
