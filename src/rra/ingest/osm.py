"""OpenStreetMap road-network ingestion (plan section 3).

Converts an OSMnx drivable graph (GraphML from ``scripts/download_data.py``) into the
project's routable graph: an undirected ``networkx.Graph`` with ``length_m``,
``highway``, ``speed_kph`` and the derived ``travel_time_min``, plus ``is_bridge`` /
``is_culvert`` flags from OSM tags.

Tag coverage is reported because the plan lists sparse OSM bridge/culvert tags as a
high-likelihood risk — better to measure it than assume it.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx

# free-flow speeds by OSM highway class (assumed; sensitivity-checked)
DEFAULT_HIGHWAY_SPEEDS_KPH: dict[str, float] = {
    "motorway": 80.0,
    "trunk": 65.0,
    "primary": 55.0,
    "secondary": 50.0,
    "tertiary": 45.0,
    "unclassified": 35.0,
    "residential": 30.0,
    "living_street": 20.0,
    "service": 25.0,
    "track": 15.0,
    "path": 10.0,
    "_default": 30.0,
}


def _first(value):
    """OSM tags can be scalars or lists (multi-edge); take the first."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _is_yes(value) -> bool:
    s = str(value).strip().lower()
    return s not in ("", "no", "false", "none", "nan")


def speed_for(highway, class_speeds: dict | None = None) -> float:
    speeds = {**DEFAULT_HIGHWAY_SPEEDS_KPH, **(class_speeds or {})}
    return float(speeds.get(str(_first(highway) or "").strip(), speeds["_default"]))


def graph_from_osm_nx(g, class_speeds: dict | None = None) -> nx.Graph:
    """Convert an OSMnx MultiDiGraph into an undirected routable graph.

    Parallel directed edges collapse to the fastest one; nodes keep their lat/lon.
    """
    out = nx.Graph()
    for n, data in g.nodes(data=True):
        out.add_node(n, x=data.get("x"), y=data.get("y"), kind="junction")
    for u, v, data in g.edges(data=True):
        length = float(data.get("length", 0.0) or 0.0)
        highway = _first(data.get("highway"))
        sp = speed_for(highway, class_speeds)
        tt = (length / 1000.0) / sp * 60.0 if sp > 0 else float("inf")
        tunnel = _first(data.get("tunnel"))
        is_bridge = _is_yes(_first(data.get("bridge")))
        is_culvert = str(tunnel).lower() == "culvert" or _is_yes(_first(data.get("culvert")))

        if out.has_edge(u, v):
            if tt < out.edges[u, v]["travel_time_min"]:  # keep the fastest parallel edge
                out.edges[u, v].update(
                    length_m=length, highway=highway, speed_kph=sp, travel_time_min=tt,
                    is_bridge=is_bridge, is_culvert=is_culvert,
                )
        else:
            out.add_edge(
                u, v, length_m=length, highway=highway, speed_kph=sp, travel_time_min=tt,
                is_bridge=is_bridge, is_culvert=is_culvert,
            )
    return out


def tag_coverage(g: nx.Graph) -> dict:
    """Bridge/culvert tag coverage on the converted graph."""
    n = g.number_of_edges()
    bridges = sum(1 for *_, d in g.edges(data=True) if d.get("is_bridge"))
    culverts = sum(1 for *_, d in g.edges(data=True) if d.get("is_culvert"))
    return {
        "n_edges": n,
        "n_bridges": bridges,
        "n_culverts": culverts,
        "bridge_share": bridges / n if n else 0.0,
        "culvert_share": culverts / n if n else 0.0,
    }


HEALTH_AMENITIES = {"hospital", "clinic", "doctors"}
SCHOOL_AMENITIES = {"school", "college", "kindergarten"}


def _point_xy(geom):
    """Return (x, y) for a point, or the centroid of a polygon/line."""
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Point":
        return float(geom.x), float(geom.y)
    c = geom.centroid
    return float(c.x), float(c.y)


def extract_facilities(features) -> dict:
    """Split OSM amenity features into the pipeline's 'health' and 'school' types."""
    out: dict = {"health": [], "school": []}
    if features is None or len(features) == 0:
        return out
    for _, row in features.iterrows():
        amenity = str(row.get("amenity", "")).strip().lower()
        xy = _point_xy(row.geometry)
        if xy is None:
            continue
        rec = {"x": xy[0], "y": xy[1], "name": row.get("name")}
        if amenity in HEALTH_AMENITIES:
            out["health"].append(rec)
        elif amenity in SCHOOL_AMENITIES:
            out["school"].append(rec)
    return out


def extract_habitations(places) -> list:
    """Habitation points from OSM place features (name + optional population)."""
    out: list = []
    if places is None or len(places) == 0:
        return out
    for _, row in places.iterrows():
        xy = _point_xy(row.geometry)
        if xy is None:
            continue
        pop = row.get("population")
        try:
            pop = float(str(pop).replace(",", "")) if pop is not None else None
        except (TypeError, ValueError):
            pop = None
        out.append(
            {"x": xy[0], "y": xy[1], "name": row.get("name"),
             "place": row.get("place"), "population": pop}
        )
    return out


def infer_crossings(edges, water) -> list:
    """Indices of road edges that cross a water feature (bridge/culvert candidates).

    This is the plan's mitigation for sparse tags: where OSM leaves a culvert untagged,
    a road crossing a stream or water body is very likely a structure. Edges are matched
    against water geometries with a spatial index.
    """
    if edges is None or len(edges) == 0 or water is None or len(water) == 0:
        return []
    from shapely.strtree import STRtree

    wgeoms = [g for g in water.geometry if g is not None and not g.is_empty]
    if not wgeoms:
        return []
    tree = STRtree(wgeoms)
    hits: list = []
    for idx, geom in edges.geometry.items():
        if geom is None or geom.is_empty:
            continue
        for j in tree.query(geom):
            if geom.intersects(wgeoms[int(j)]):
                hits.append(idx)
                break
    return hits


def load_osm_graphml(path: str | Path) -> nx.Graph:
    """Load a GraphML written by OSMnx and convert it to the routable graph."""
    import osmnx as ox

    g = ox.load_graphml(path)
    return graph_from_osm_nx(g)
