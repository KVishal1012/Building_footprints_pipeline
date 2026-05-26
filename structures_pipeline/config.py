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
    parcel_sources: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.output_dir = Path(self.output_dir)
        self.raw_dir = Path(self.raw_dir)
        self.cache_dir = Path(self.cache_dir)
        self.sql_footprint_source = dict(self.sql_footprint_source or {})
        self.parcel_sources = dict(self.parcel_sources)

    @property
    def cities_output_dir(self) -> Path:
        return self.output_dir / "cities"

    @property
    def master_output_dir(self) -> Path:
        return self.output_dir / "structures_master"

    @property
    def manifest_dir(self) -> Path:
        return self.output_dir / "manifests"

    @property
    def qa_dir(self) -> Path:
        return self.output_dir / "qa"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.output_dir,
            self.raw_dir,
            self.cache_dir,
            self.cities_output_dir,
            self.master_output_dir,
            self.manifest_dir,
            self.qa_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
