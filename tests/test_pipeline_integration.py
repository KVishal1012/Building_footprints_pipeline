import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from structures_pipeline.config import PipelineConfig
from structures_pipeline.geometry import empty_gdf
from structures_pipeline.pipeline import build_places


def test_two_city_run_writes_outputs(monkeypatch, tmp_path):
    places = gpd.GeoDataFrame(
        {
            "PlaceGEOID": ["1714000", "4827000"],
            "StateFP": ["17", "48"],
            "PlaceFP": ["14000", "27000"],
            "City": ["Chicago", "Houston"],
            "State": ["Illinois", "Texas"],
            "StateAbbr": ["IL", "TX"],
            "CensusYear": [2025, 2025],
        },
        geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)],
        crs="EPSG:4326",
    )

    def fake_overture(place, boundary, config, release):
        minx, miny, _, _ = boundary.total_bounds
        return gpd.GeoDataFrame(
            {
                "StructureID": [f"ovt_{place['PlaceGEOID']}"],
                "FootprintSource": ["overture"],
                "OvertureID": [f"ovt_source_{place['PlaceGEOID']}"],
                "MicrosoftID": [pd.NA],
                "OvertureClass": ["residential"],
                "OvertureSubtype": [pd.NA],
                "Stories_OVT": [2],
                "Height_OVT": [6.1],
                "Height_MS": [pd.NA],
                "FootprintAssignmentMethod": ["representative_point_within"],
                "FootprintAssignmentOverlapRatio": [pd.NA],
            },
            geometry=[box(minx + 0.1, miny + 0.1, minx + 0.2, miny + 0.2)],
            crs="EPSG:4326",
        )

    monkeypatch.setattr("structures_pipeline.pipeline.resolve_overture_release", lambda config: "test-release")
    monkeypatch.setattr("structures_pipeline.pipeline.load_overture_buildings", fake_overture)
    monkeypatch.setattr("structures_pipeline.pipeline.load_microsoft_fallback", lambda *args, **kwargs: empty_gdf())
    monkeypatch.setattr("structures_pipeline.pipeline.get_osm_buildings", lambda *args, **kwargs: empty_gdf())
    monkeypatch.setattr("structures_pipeline.pipeline.get_nsi_structures", lambda *args, **kwargs: gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"))
    monkeypatch.setattr("structures_pipeline.pipeline.get_acs_household_size", lambda *args, **kwargs: (2.5, "ACS test"))

    config = PipelineConfig(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "out",
        raw_dir=tmp_path / "raw",
        cache_dir=tmp_path / "cache",
        download_missing=False,
        use_nsi=False,
        use_census=True,
    )

    result = build_places(places, config=config)

    assert len(result["city_paths"]) == 2
    assert all(path.exists() for path in result["city_paths"])
    assert result["master_path"].exists()
    assert result["qa_path"].exists()
    assert result["manifest_path"].exists()
