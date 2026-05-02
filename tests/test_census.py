import geopandas as gpd
from shapely.geometry import box

from structures_pipeline.census import normalize_places, parse_place


def test_parse_place_normalizes_state_abbreviation():
    assert parse_place("Chicago, IL") == {"city": "Chicago", "state": "Illinois"}


def test_normalize_places_excludes_puerto_rico_and_keeps_per_place_rows():
    raw = gpd.GeoDataFrame(
        {
            "STATEFP": ["17", "17", "72"],
            "PLACEFP": ["14000", "99999", "12345"],
            "GEOID": ["1714000", "1799999", "7212345"],
            "NAME": ["Chicago", "Example", "PR Place"],
            "NAMELSAD": ["Chicago city", "Example village", "PR Place"],
            "LSAD": ["25", "47", "25"],
            "FUNCSTAT": ["A", "A", "A"],
        },
        geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3), box(4, 4, 5, 5)],
        crs="EPSG:4326",
    )

    places = normalize_places(raw, 2025)

    assert places["PlaceGEOID"].tolist() == ["1714000", "1799999"]
    assert len(places) == 2
