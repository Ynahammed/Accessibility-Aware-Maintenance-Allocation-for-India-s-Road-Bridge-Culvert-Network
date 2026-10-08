import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

from rra.ingest import osm


def test_extract_facilities_splits_health_and_school():
    gdf = gpd.GeoDataFrame(
        {"amenity": ["hospital", "school", "cafe"], "name": ["H", "S", "C"]},
        geometry=[Point(76.3, 9.2), Point(76.31, 9.21), Point(76.32, 9.22)],
    )
    out = osm.extract_facilities(gdf)
    assert len(out["health"]) == 1
    assert len(out["school"]) == 1
    assert out["health"][0]["x"] == 76.3


def test_extract_habitations_parses_population():
    gdf = gpd.GeoDataFrame(
        {"place": ["village", "town"], "name": ["A", "B"], "population": ["1,234", "50"]},
        geometry=[Point(0, 0), Point(1, 1)],
    )
    out = osm.extract_habitations(gdf)
    assert out[0]["population"] == 1234.0
    assert out[1]["place"] == "town"


def test_infer_crossings_finds_edges_over_water():
    edges = gpd.GeoDataFrame(
        {"id": [0, 1]},
        geometry=[LineString([(0, 0), (2, 0)]), LineString([(0, 5), (2, 5)])],
        index=[10, 11],
    )
    water = gpd.GeoDataFrame(
        geometry=[Polygon([(1, -1), (1.2, -1), (1.2, 1), (1, 1)])]
    )
    hits = osm.infer_crossings(edges, water)
    assert hits == [10]  # only the edge at y=0 crosses the water polygon


def test_infer_crossings_handles_empty_inputs():
    edges = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 0)])])
    assert osm.infer_crossings(edges, None) == []
    assert osm.infer_crossings(None, edges) == []
    assert osm.infer_crossings(edges, gpd.GeoDataFrame(geometry=[])) == []
