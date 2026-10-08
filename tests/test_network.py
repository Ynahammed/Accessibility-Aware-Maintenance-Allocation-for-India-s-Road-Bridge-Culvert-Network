import networkx as nx
import pytest

from rra.network import build
from rra.network.attach_assets import attach_structures, split_edge


def tiny_graph():
    # a 3-junction line, 1 km per segment, rural; positions in metres
    junctions = [(1, 0, 0), (2, 1000, 0), (3, 2000, 0)]
    roads = [(1, 2, 1000, "rural"), (2, 3, 1000, "rural")]
    return build.build_network(junctions, roads)


def test_travel_time_basic():
    # 1 km at 30 km/h = 2 minutes
    assert build.travel_time_minutes(1000, 30) == pytest.approx(2.0)
    assert build.travel_time_minutes(0, 30) == 0.0


def test_travel_time_rejects_bad_input():
    with pytest.raises(ValueError):
        build.travel_time_minutes(-1, 30)
    with pytest.raises(ValueError):
        build.travel_time_minutes(100, 0)


def test_build_sets_edge_attributes():
    g = tiny_graph()
    assert g.number_of_nodes() == 3
    assert g.number_of_edges() == 2
    d = g.edges[1, 2]
    assert d["length_m"] == 1000
    assert d["road_class"] == "rural"
    assert d["speed_kph"] == 30
    assert d["travel_time_min"] == pytest.approx(2.0)


def test_build_rejects_unknown_junction():
    with pytest.raises(KeyError):
        build.build_network([(1, 0, 0)], [(1, 99, 1000, "rural")])


def test_add_road_rejects_unknown_class():
    g = build.new_graph()
    build.add_junction(g, 1, 0, 0)
    build.add_junction(g, 2, 1, 0)
    with pytest.raises(ValueError):
        build.add_road(g, 1, 2, 1000, "motorway")


def test_snap_attaches_within_tolerance_and_logs_overshoot():
    g = tiny_graph()
    points = [
        ("h1", 10, 10, "habitation"),      # near junction 1
        ("h2", 5000, 5000, "habitation"),  # far away -> overshoot
    ]
    res = build.snap_points(g, points, tolerance_m=25.0, node_pool=[1, 2, 3])
    assert "h1" in res.attached
    assert res.attached["h1"].startswith("habitation:")
    assert "h2" in res.overshot
    assert res.overshot["h2"] > 25.0


def test_split_edge_conserves_travel_time():
    g = tiny_graph()
    before = g.edges[1, 2]["travel_time_min"]
    node = split_edge(g, 1, 2, 0.5, "B1", "minor_bridge")
    assert node in g
    assert g.nodes[node]["kind"] == "structure"
    total = g.edges[1, node]["travel_time_min"] + g.edges[node, 2]["travel_time_min"]
    assert total == pytest.approx(before)
    # original edge gone
    assert not g.has_edge(1, 2)


def test_split_edge_rejects_bad_fraction():
    g = tiny_graph()
    with pytest.raises(ValueError):
        split_edge(g, 1, 2, 0.0, "B1")
    with pytest.raises(ValueError):
        split_edge(g, 1, 2, 1.0, "B1")


def test_attach_structures_returns_mapping():
    g = tiny_graph()
    m = attach_structures(g, [("B1", 1, 2, 0.3, "culvert")])
    assert m["B1"] == "structure:B1"


def test_qa_report_passes_when_habitations_reach_health():
    g = tiny_graph()
    res = build.snap_points(
        g,
        [("h1", 0, 0, "habitation"), ("h2", 2000, 0, "habitation"),
         ("f1", 2000, 0, "facility")],
        tolerance_m=25.0,
        node_pool=[1, 2, 3],
    )
    rep = build.qa_report(
        g,
        facility_nodes={"health": [res.attached["f1"]]},
        habitation_nodes=[res.attached["h1"], res.attached["h2"]],
    )
    assert rep.passes is True
    assert rep.share_habitations_with_health == 1.0
    assert rep.n_orphan_facilities == 0
    assert "PASS" in rep.to_markdown()


def test_snapped_assets_are_routable():
    import networkx as nx

    g = tiny_graph()
    res = build.snap_points(
        g, [("h1", 10, 0, "habitation")], tolerance_m=25.0, node_pool=[1, 2, 3]
    )
    # the snapped node is connected to its host junction, not floating
    assert nx.has_path(g, res.attached["h1"], 3)


def test_qa_report_rejects_when_habitations_cannot_reach_health():
    # main component 1-2-3 with the health facility; isolated junction 4 with a habitation
    g = build.build_network(
        [(1, 0, 0), (2, 1000, 0), (3, 2000, 0), (4, 50000, 50000)],
        [(1, 2, 1000, "rural"), (2, 3, 1000, "rural")],
    )
    res = build.snap_points(
        g,
        [("h9", 50000, 50000, "habitation"), ("f1", 0, 0, "facility")],
        tolerance_m=25.0,
        node_pool=[1, 2, 3, 4],
    )
    rep = build.qa_report(
        g,
        facility_nodes={"health": [res.attached["f1"]]},
        habitation_nodes=[res.attached["h9"]],
    )
    assert rep.passes is False
    assert rep.share_habitations_with_health == 0.0
    assert rep.n_orphan_facilities == 1
    assert "REJECT" in rep.to_markdown()
