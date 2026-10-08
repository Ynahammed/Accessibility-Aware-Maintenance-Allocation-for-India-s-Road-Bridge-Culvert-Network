"""Plan 5.3 toy tests + a brute-force cross-check of the Dijkstra speed-up.

Hand-built networks where the right answer is known:
  * a single bridge on the only route cuts off its population,
  * two parallel routes cost zero individually and a lot jointly (non-additivity),
  * loss is non-negative and monotone as assets are added to F.
"""

import copy
import random

import networkx as nx
import pytest

from rra.consequence.accessibility import (
    INF,
    AccessibilityModel,
    _multi_source_dijkstra,
)
from rra.network import build


def _model(g, habitations, facilities, caps, weights):
    return AccessibilityModel(g, habitations, facilities, caps, weights)


def single_bridge_graph():
    """h -- m(bridge) -- f, each leg 600 m rural (1.2 min). tau0 = 2.4 min."""
    g = build.new_graph()
    build.add_point(g, "h", 0, 0, "habitation")
    build.add_point(g, "m", 500, 0, "structure")
    build.add_point(g, "f", 1000, 0, "facility")
    build.add_road(g, "h", "m", 600, "rural")
    build.add_road(g, "m", "f", 600, "rural")
    return g


def parallel_routes_graph():
    """h ==two disjoint routes== f, each with its own bridge, each 1.8 min."""
    g = build.new_graph()
    build.add_point(g, "h", 0, 0, "habitation")
    build.add_point(g, "f", 3000, 0, "facility")
    for tag in ("a", "b"):
        build.add_point(g, f"{tag}1", 500, 0, "junction")
        build.add_point(g, f"m_{tag}", 1500, 0, "structure")
        build.add_road(g, "h", f"{tag}1", 300, "rural")
        build.add_road(g, f"{tag}1", f"m_{tag}", 300, "rural")
        build.add_road(g, f"m_{tag}", "f", 300, "rural")
    return g


def brute_loss(model, failed_edges=(), failed_nodes=()):
    """Reference: physically remove failures and recompute from scratch."""
    g = copy.deepcopy(model.graph)
    g.remove_nodes_from(failed_nodes)
    g.remove_edges_from([e for e in failed_edges if g.has_edge(*e)])
    total = 0.0
    for k, srcs in model.facilities.items():
        live = [s for s in srcs if s in g]
        dist, _ = _multi_source_dijkstra(g, live, frozenset(), frozenset())
        cap = model.caps_min[k]
        w = model.weights[k]
        for h, pop in model.habitations.items():
            phi_f = 1.0 if h not in g else model._phi(dist.get(h, INF), cap)
            total += pop * w * (phi_f - model._baseline_phi[k][h])
    return total


# --- exact hand checks ------------------------------------------------------------


def test_single_bridge_on_only_route_cuts_off_population():
    g = single_bridge_graph()
    m = _model(g, {"h": 100.0}, {"health": ["f"]}, {"health": 60.0}, {"health": 1.0})
    # baseline tau0 = 2.4 min, phi0 = 0.04; failing the bridge -> phi = 1
    assert m.baseline_times("health")["h"] == pytest.approx(2.4)
    expected = 100.0 * 1.0 * (1.0 - 0.04)
    assert m.loss(failed_nodes=["m"]) == pytest.approx(expected)


def test_no_failure_is_zero():
    g = single_bridge_graph()
    m = _model(g, {"h": 100.0}, {"health": ["f"]}, {"health": 60.0}, {"health": 1.0})
    assert m.loss() == 0.0


def test_parallel_routes_are_non_additive():
    g = parallel_routes_graph()
    m = _model(g, {"h": 100.0}, {"health": ["f"]}, {"health": 60.0}, {"health": 1.0})
    alone_a = m.loss(failed_nodes=["m_a"])
    alone_b = m.loss(failed_nodes=["m_b"])
    jointly = m.loss(failed_nodes=["m_a", "m_b"])
    assert alone_a == 0.0
    assert alone_b == 0.0
    assert jointly > 0.0
    # the whole point: sum of individual losses understates the joint loss
    assert alone_a + alone_b < jointly


def test_loss_is_nonnegative_and_monotone():
    g = parallel_routes_graph()
    m = _model(g, {"h": 100.0}, {"health": ["f"]}, {"health": 60.0}, {"health": 1.0})
    assert m.loss() == 0.0
    assert m.loss(failed_nodes=["m_a"]) >= 0.0
    assert m.loss(failed_nodes=["m_a", "m_b"]) >= m.loss(failed_nodes=["m_a"])


def test_affected_habitations_is_targeted():
    g = single_bridge_graph()
    m = _model(g, {"h": 100.0}, {"health": ["f"]}, {"health": 60.0}, {"health": 1.0})
    # the bridge m is on h's baseline path
    assert m.affected_habitations("health", failed_nodes=["m"]) == {"h"}
    # an unrelated edge does not touch h
    assert m.affected_habitations("health", failed_edges=[]) == set()


def test_multiple_facility_types_accumulate():
    g = single_bridge_graph()
    m = _model(
        g,
        {"h": 100.0},
        {"health": ["f"], "school": ["f"]},
        {"health": 60.0, "school": 30.0},
        {"health": 1.0, "school": 0.5},
    )
    # tau0 = 2.4 for both: phi_h = 0.04, phi_s = 0.08
    expected = 100.0 * (1.0 * (1 - 0.04) + 0.5 * (1 - 0.08))
    assert m.loss(failed_nodes=["m"]) == pytest.approx(expected)


def test_societal_cost_scales_with_outage_days():
    g = single_bridge_graph()
    m = _model(g, {"h": 100.0}, {"health": ["f"]}, {"health": 60.0}, {"health": 1.0})
    assert m.societal_cost(10.0, failed_nodes=["m"]) == pytest.approx(
        10.0 * m.loss(failed_nodes=["m"])
    )


def test_validate_raises_on_unknown_failure():
    g = single_bridge_graph()
    m = _model(g, {"h": 100.0}, {"health": ["f"]}, {"health": 60.0}, {"health": 1.0})
    with pytest.raises(KeyError):
        m.loss(failed_nodes=["nope"], validate=True)


# --- brute-force cross-check of the speed-up --------------------------------------


def random_graph(seed: int, n: int = 12):
    rng = random.Random(seed)
    g = build.new_graph()
    for i in range(n):
        build.add_junction(g, i, rng.uniform(0, 10000), rng.uniform(0, 10000))
    order = list(range(n))
    rng.shuffle(order)
    for i in range(1, n):  # spanning tree -> connected
        build.add_road(g, order[i], order[rng.randrange(i)], rng.uniform(200, 2000), "rural")
    for _ in range(n // 2):  # chords -> cycles (non-additivity)
        u, v = rng.randrange(n), rng.randrange(n)
        if u != v and not g.has_edge(u, v):
            build.add_road(g, u, v, rng.uniform(200, 2000), "rural")
    return g, rng


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_loss_matches_brute_force(seed):
    g, rng = random_graph(seed)
    nodes = list(g.nodes)
    habitations = {n: rng.uniform(10, 100) for n in nodes}
    facility = rng.choice(nodes)
    m = _model(
        g, habitations, {"health": [facility]}, {"health": 60.0}, {"health": 1.0}
    )
    edges = list(g.edges())
    for _ in range(25):
        k_e = rng.randrange(0, 4)
        failed_edges = [edges[rng.randrange(len(edges))] for _ in range(k_e)]
        assert m.loss(failed_edges=failed_edges) == pytest.approx(
            brute_loss(m, failed_edges=failed_edges), abs=1e-9
        )


@pytest.mark.parametrize("seed", [5, 6, 7])
def test_loss_with_failed_nodes_matches_brute_force(seed):
    g, rng = random_graph(seed)
    nodes = list(g.nodes)
    habitations = {n: rng.uniform(10, 100) for n in nodes}
    m = _model(g, habitations, {"health": [nodes[0]]}, {"health": 60.0}, {"health": 1.0})
    for _ in range(15):
        k_n = rng.randrange(1, 3)
        failed_nodes = [rng.choice(nodes) for _ in range(k_n)]
        assert m.loss(failed_nodes=failed_nodes) == pytest.approx(
            brute_loss(m, failed_nodes=failed_nodes), abs=1e-9
        )
