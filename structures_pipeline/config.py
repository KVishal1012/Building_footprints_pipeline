from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PipelineConfig:
    data_dir: Path = Path("data")
    output_dir: Path = Path("data/output")
    raw_dir: Path = Path("data/raw")
    cache_dir: Path = Path("cache")
    country: str = "USA"
    source_version: str = "latest"
    census_year: int = 2025
    download_missing: bool = True
    overwrite_raw: bool = False
    use_overture: bool = True
    use_microsoft: bool = True
    use_sql: bool = True
    use_osm: bool = False
    use_nsi: bool = True
    use_census: bool = True
    use_parcels: bool = True
    add_microsoft_fallback: bool = True
    microsoft_zoom: int = 9
    microsoft_overlap_ratio_threshold: float = 0.10
    nsi_tile_size_deg: float = 0.08
    request_timeout_sec: int = 90
    parcel_overlap_ratio_threshold: float = 0.05
    cache_remote_parcels: bool = True
    sql_footprint_source: dict | None = None
    sql_baseline_source: dict | None = None
    sql_export: dict | None = None
    return_dataframe: bool = False
    dataframe_preview_rows: int = 10
    write_local_outputs: bool = True
    use_ai_predictions: bool = False
    ai_model_dir: Path = Path("models/us_structure_ai")
    ai_prediction_mode: str = "suggest_only"
    ai_min_confidence: float = 0.70
    updated_by: str = "structures_pipeline"
    release_id: str | None = None
    refresh_metadata: dict | None = None
    coverage_config: dict | None = None
    delivery_formats: list[str] = field(default_factory=list)
    delivery_output_dir: Path = Path("data/delivery")
    postgis_export: dict | None = None
    domain_extensions: list[str] = field(default_factory=list)
    parcel_sources: dict[str, dict] = field(default_factory=dict)

    # Normalize path and optional dict-like settings after dataclass creation.
    def __post_init__(self) -> None:
        """Normalize path and optional dict-like settings after dataclass creation."""
        self.data_dir = Path(self.data_dir)
        self.output_dir = Path(self.output_dir)
        self.raw_dir = Path(self.raw_dir)
        self.cache_dir = Path(self.cache_dir)
        self.ai_model_dir = Path(self.ai_model_dir)
        self.delivery_output_dir = Path(self.delivery_output_dir)
        self.sql_footprint_source = dict(self.sql_footprint_source or {})
        self.sql_baseline_source = dict(self.sql_baseline_source or {})
        self.sql_export = dict(self.sql_export or {})
        self.refresh_metadata = dict(self.refresh_metadata or {})
        self.coverage_config = dict(self.coverage_config or {})
        self.delivery_formats = list(self.delivery_formats or [])
        self.postgis_export = dict(self.postgis_export or {})
        self.domain_extensions = list(self.domain_extensions or [])
        self.parcel_sources = dict(self.parcel_sources)

    # Directory for per-place GeoParquet outputs partitioned by state FIPS.
    @property
    def cities_output_dir(self) -> Path:
        """Directory for per-place GeoParquet outputs partitioned by state FIPS."""
        return self.output_dir / "cities"

    # Directory for the combined multi-place master dataset.
    @property
    def master_output_dir(self) -> Path:
        """Directory for the combined multi-place master dataset."""
        return self.output_dir / "structures_master"

    # Directory for reproducibility manifests that describe each run.
    @property
    def manifest_dir(self) -> Path:
        """Directory for reproducibility manifests that describe each run."""
        return self.output_dir / "manifests"

    # Directory for city-level QA metrics and validation artifacts.
    @property
    def qa_dir(self) -> Path:
        """Directory for city-level QA metrics and validation artifacts."""
        return self.output_dir / "qa"

    # Create every directory the pipeline may write to during a run.
    def ensure_dirs(self) -> None:
        """Create every directory the pipeline may write to during a run."""
        for path in (
            self.data_dir,
            self.output_dir,
            self.raw_dir,
            self.cache_dir,
            self.delivery_output_dir,
            self.cities_output_dir,
            self.master_output_dir,
            self.manifest_dir,
            self.qa_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
