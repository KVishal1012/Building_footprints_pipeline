"""Local-only settings for the Chennai real-source and Supabase refresh runners."""

from pathlib import Path

CHENNAI_SOURCE_ROOT = Path(
    "/absolute/path/to/geoai-intelligence-system/data/chennai_2015"
)
OSM_BUILDINGS_PATH = CHENNAI_SOURCE_ROOT / "raw/osm/buildings.geojson"
GCC_WARDS_PATH = CHENNAI_SOURCE_ROOT / "raw/gcc/gcc_wards.geojson"
SOURCE_MANIFEST_PATH = CHENNAI_SOURCE_ROOT / "source_manifest.json"

CANONICAL_OUTPUT_PATH = Path("data/local/india/chennai/structures.parquet")
EXPOSURE_OUTPUT_PATH = Path("data/local/india/chennai/structure_exposure.json")
ACCEPTANCE_REPORT_PATH = Path("data/derived/chennai_real_source_report.json")
LIFECYCLE_REPORT_PATH = Path("data/derived/chennai_supabase_lifecycle_report.json")

SUPABASE_URL = None
SUPABASE_SERVICE_ROLE_ENV = "SUPABASE_SERVICE_ROLE_KEY"
SUPABASE_STORE = "in_memory"
DRY_RUN = True
PROMOTE_TO_CANONICAL = True

# Optional deterministic override. Leave as None to stamp the current UTC time.
DATA_REFRESH_TIMESTAMP = None
