import networkx as nx
import pytest

from rra.ingest import osm


def multi_digraph():
    g = nx.MultiDiGraph()
    g.add_node(1, x=76.3, y=9.2)
    g.add_node(2, x=76.31, y=9.2)
    g.add_node(3, x=76.32, y=9.2)
    g.add_edge(1, 2, length=1000.0, highway="primary")
    g.add_edge(2, 1, length=1000.0, highway="primary")
    g.add_edge(2, 3, length=500.0, highway="residential", bridge="yes")
    return g


def test_conversion_builds_undirected_routable_graph():
    g = osm.graph_from_osm_nx(multi_digraph())
    assert not g.is_directed()
    assert g.number_of_edges() == 2  # parallel directed edges collapsed
    e = g.edges[1, 2]
    assert e["length_m"] == 1000.0
    assert e["highway"] == "primary"
    assert e["speed_kph"] == 55.0
    assert e["travel_time_min"] == pytest.approx((1000 / 1000) / 55.0 * 60.0)


def test_bridge_and_culvert_flags_and_coverage():
    g = multi_digraph()
    g.add_edge(3, 1, length=300.0, highway="track", tunnel="culvert")
    out = osm.graph_from_osm_nx(g)
    assert out.edges[2, 3]["is_bridge"] is True
    assert out.edges[3, 1]["is_culvert"] is True
    cov = osm.tag_coverage(out)
    assert cov["n_bridges"] == 1
    assert cov["n_culverts"] == 1
    assert cov["n_edges"] == 3
    assert 0 < cov["bridge_share"] < 1


def test_handles_list_valued_tags():
    g = nx.MultiDiGraph()
    g.add_node(1, x=0, y=0)
    g.add_node(2, x=1, y=0)
    g.add_edge(1, 2, length=100.0, highway=["secondary", "tertiary"])
    out = osm.graph_from_osm_nx(g)
    assert out.edges[1, 2]["highway"] == "secondary"
    assert out.edges[1, 2]["speed_kph"] == 50.0


def test_unknown_highway_uses_default_speed():
    g = nx.MultiDiGraph()
    g.add_node(1, x=0, y=0)
    g.add_node(2, x=1, y=0)
    g.add_edge(1, 2, length=100.0, highway="made_up")
    assert osm.graph_from_osm_nx(g).edges[1, 2]["speed_kph"] == 30.0
