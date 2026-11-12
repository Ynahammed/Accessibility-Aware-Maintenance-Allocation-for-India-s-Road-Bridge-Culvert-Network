"""Clip Geofabrik Southern Zone OSM data to Alappuzha district.

Requires the project's existing geopandas, pyogrio, networkx, and shapely packages.
The PBF is read directly by GDAL's OSM driver. Outputs are kept separate from the
older town-area data/raw/osm dataset.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
import pyogrio
from pyproj import Geod
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data/raw/geofabrik/southern-zone-latest.osm.pbf"
BOUNDARY = ROOT / "data/raw/boundaries/kerala_districts_census_2011.geojson"
OUTPUT = ROOT / "data/raw/osm_alappuzha_district"

PLACE_TYPES = {"city", "town", "village", "hamlet", "isolated_dwelling", "suburb"}
HEALTH_AMENITIES = {"hospital", "clinic", "doctors"}
SCHOOL_AMENITIES = {"school", "college", "kindergarten"}
HEALTHCARE_TYPES = {"hospital", "clinic", "doctor", "health_post"}
TAG_RE = re.compile(r'"([^"]+)"\s*=>\s*"((?:[^"\\]|\\.)*)"')
GEOD = Geod(ellps="WGS84")


def tags_of(value) -> dict[str, str]:
    if value is None:
        return {}
    try:
        if pd.isna(value):
            return {}
    except (TypeError, ValueError):
        pass
    tags = {}
    for match in TAG_RE.finditer(str(value)):
        key = match.group(1)
        val = match.group(2).replace(r"\"", '"').replace(r"\\", "\\")
        tags[key] = val
    return tags


def text(value, default="") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return str(value)


def field(row, key, default=None):
    value = row.get(key, default)
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return value


def lines_in(geometry):
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type == "LineString":
        yield geometry
    elif geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        for part in geometry.geoms:
            yield from lines_in(part)


def read_bbox(layer: str, bounds, where: str | None = None):
    start = time.monotonic()
    print(f"Reading OSM {layer} layer...", flush=True)
    frame = pyogrio.read_dataframe(SOURCE, layer=layer, bbox=bounds, where=where)
    print(f"  {len(frame):,} candidates read in {time.monotonic() - start:.1f}s", flush=True)
    return frame


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Geofabrik PBF missing: {SOURCE}")
    if not BOUNDARY.is_file():
        raise FileNotFoundError(f"Alappuzha boundary missing: {BOUNDARY}")

    feature_collection = json.loads(BOUNDARY.read_text(encoding="utf-8"))
    alappuzha_feature = next(
        f for f in feature_collection["features"]
        if f["properties"].get("censuscode") == 598
    )
    boundary = shape(alappuzha_feature["geometry"])
    bounds = boundary.bounds
    OUTPUT.mkdir(parents=True, exist_ok=True)

    # Roads plus mapped waterways in the line layer.
    line_rows = read_bbox("lines", bounds, "highway IS NOT NULL OR waterway IS NOT NULL")
    clipped_road_rows = []
    water_rows = []
    graph = nx.MultiDiGraph()
    graph.graph.update({
        "crs": "EPSG:4326",
        "district": "Alappuzha",
        "source": "Geofabrik Southern Zone OSM extract",
        "boundary": "Census 2011 district polygon, Census code 598",
    })
    node_for_xy: dict[tuple[float, float], int] = {}

    def get_node(lon: float, lat: float) -> int:
        key = (round(lon, 8), round(lat, 8))
        if key not in node_for_xy:
            node_id = len(node_for_xy)
            node_for_xy[key] = node_id
            # OSMnx's GraphML loader expects node x/y attributes serialized as strings.
            graph.add_node(node_id, x=str(float(lon)), y=str(float(lat)))
        return node_for_xy[key]

    for index, row in line_rows.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        tags = tags_of(field(row, "other_tags"))
        highway = text(field(row, "highway"))
        waterway = text(field(row, "waterway"))
        if waterway:
            clipped_waterway = geom.intersection(boundary)
            if not clipped_waterway.is_empty:
                water_rows.append({
                    "osm_id": field(row, "osm_id"),
                    "name": field(row, "name"),
                    "waterway": waterway,
                    "geometry": clipped_waterway,
                })
        if not highway:
            continue

        clipped = geom.intersection(boundary)
        if clipped.is_empty:
            continue
        output_row = row.to_dict()
        output_row["geometry"] = clipped
        clipped_road_rows.append(output_row)

        oneway = text(tags.get("oneway"), "no").lower()
        is_oneway = oneway in {"yes", "true", "1", "-1"} or tags.get("junction") == "roundabout"
        reverse = oneway == "-1"
        common = {
            "highway": highway,
            "osmid": text(field(row, "osm_id", index)),
            "bridge": text(tags.get("bridge"), "no"),
            "culvert": text(tags.get("culvert"), "no"),
            "tunnel": text(tags.get("tunnel"), "no"),
            "name": text(field(row, "name")),
        }
        for part in lines_in(clipped):
            coords = list(part.coords)
            for start, end in zip(coords, coords[1:]):
                lon1, lat1 = float(start[0]), float(start[1])
                lon2, lat2 = float(end[0]), float(end[1])
                if round(lon1, 8) == round(lon2, 8) and round(lat1, 8) == round(lat2, 8):
                    continue
                u, v = get_node(lon1, lat1), get_node(lon2, lat2)
                _, _, length_m = GEOD.inv(lon1, lat1, lon2, lat2)
                attrs = {**common, "length": abs(float(length_m))}
                if reverse:
                    graph.add_edge(v, u, **attrs)
                else:
                    graph.add_edge(u, v, **attrs)
                if not is_oneway:
                    graph.add_edge(v, u, **attrs)

    roads = gpd.GeoDataFrame(clipped_road_rows, geometry="geometry", crs="EPSG:4326")
    roads.to_parquet(OUTPUT / "roads.parquet", index=False)
    # OSMnx's GraphML loader expects node and edge attributes serialized as strings;
    # it converts known fields (such as length) back to numeric values on load.
    for _, data in graph.nodes(data=True):
        for key, value in data.items():
            data[key] = str(value)
    for _, _, data in graph.edges(data=True):
        for key, value in data.items():
            data[key] = str(value)
    nx.write_graphml(graph, OUTPUT / "roads.graphml", encoding="utf-8")
    print(
        f"Wrote {len(roads):,} road ways; graph {graph.number_of_nodes():,} nodes / "
        f"{graph.number_of_edges():,} directed edges",
        flush=True,
    )

    # Area features supply mapped lakes/reservoirs, settlements and facility polygons.
    polygons = read_bbox("multipolygons", bounds)
    places, facilities = [], []
    for index, row in polygons.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        tags = tags_of(field(row, "other_tags"))
        water_type = text(field(row, "water")) or tags.get("water", "")
        natural = text(field(row, "natural")) or tags.get("natural", "")
        amenity = text(field(row, "amenity")) or tags.get("amenity", "")
        place = text(field(row, "place")) or tags.get("place", "")
        name = field(row, "name") or tags.get("name")
        clipped = geom.intersection(boundary)
        if clipped.is_empty:
            continue
        if natural == "water" or water_type:
            water_rows.append({
                "osm_id": field(row, "osm_id"),
                "name": name,
                "waterway": water_type or natural,
                "geometry": clipped,
            })
        if place in PLACE_TYPES:
            places.append({
                "osm_id": field(row, "osm_id"),
                "name": name,
                "place": place,
                "population": tags.get("population"),
                "geometry": clipped.centroid,
            })
        healthcare = tags.get("healthcare", "")
        if amenity in HEALTH_AMENITIES | SCHOOL_AMENITIES or healthcare in HEALTHCARE_TYPES:
            facilities.append({
                "osm_id": field(row, "osm_id"),
                "name": name,
                "amenity": amenity or healthcare,
                "geometry": clipped.centroid,
            })

    # Points contain settlement nodes and health/school POIs.
    point_rows = read_bbox("points", bounds)
    for _, row in point_rows.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty or not boundary.covers(geom):
            continue
        tags = tags_of(field(row, "other_tags"))
        place = text(field(row, "place")) or tags.get("place", "")
        amenity = text(field(row, "amenity")) or tags.get("amenity", "")
        healthcare = tags.get("healthcare", "")
        name = field(row, "name") or tags.get("name")
        if place in PLACE_TYPES:
            places.append({
                "osm_id": field(row, "osm_id"),
                "name": name,
                "place": place,
                "population": tags.get("population"),
                "geometry": geom,
            })
        if amenity in HEALTH_AMENITIES | SCHOOL_AMENITIES or healthcare in HEALTHCARE_TYPES:
            facilities.append({
                "osm_id": field(row, "osm_id"),
                "name": name,
                "amenity": amenity or healthcare,
                "geometry": geom,
            })

    water_gdf = gpd.GeoDataFrame(water_rows, geometry="geometry", crs="EPSG:4326")
    place_gdf = gpd.GeoDataFrame(places, geometry="geometry", crs="EPSG:4326")
    facility_gdf = gpd.GeoDataFrame(facilities, geometry="geometry", crs="EPSG:4326")
    water_gdf.to_parquet(OUTPUT / "water.parquet", index=False)
    place_gdf.to_parquet(OUTPUT / "places.parquet", index=False)
    facility_gdf.to_parquet(OUTPUT / "facilities.parquet", index=False)

    report = [
        "# Alappuzha district OSM clip", "",
        "- Source: Geofabrik Southern Zone OSM PBF at `data/raw/geofabrik/southern-zone-latest.osm.pbf`.",
        "- OSM snapshot: data through 2026-11-04T21:21:03Z; source licensed under ODbL 1.0.",
        "- Clip: Census 2011 Alappuzha polygon, Census code 598; CRS EPSG:4326.",
        "- This is volunteered OSM mapping, not an authoritative PWD inventory or completeness guarantee.", "",
        "## Extracted layers", "",
        f"- Road ways: {len(roads):,}",
        f"- Routable graph: {graph.number_of_nodes():,} nodes; {graph.number_of_edges():,} directed edges",
        f"- Waterways/water bodies: {len(water_gdf):,}",
        f"- Settlement/place features: {len(place_gdf):,}",
        f"- Health/school features: {len(facility_gdf):,}", "",
        "These district files are separate from the older town-area network under `data/raw/osm/`.", "",
    ]
    (OUTPUT / "README.md").write_text("\n".join(report), encoding="utf-8")
    print("Wrote district clip outputs to", OUTPUT, flush=True)


if __name__ == "__main__":
    main()
