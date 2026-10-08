"""Accessibility-loss consequence model (plan section 5.3).

This replaces traffic-volume criticality. For a failure set ``F``:

    L(F) = sum_{h in H} sum_{k in K} P_h w_k [ phi(tau^F_k(h)) - phi(tau^0_k(h)) ]
    phi(tau) = min(tau / T_k, 1)          (unreachable -> phi = 1)

``tau^0_k(h)`` is travel time on the intact network; ``tau^F_k(h)`` with all assets in F
removed. Societal cost of an event is ``C(F) = D * L(F)`` with D the outage days.

Why it is implemented on sets
-----------------------------
Two parallel routes each cost zero alone and a lot together, so ``L`` is computed on the
whole failure set, never summed per asset. Both the exactness of that property and the
Dijkstra speed-up are asserted on hand-built toy graphs in ``tests/test_accessibility.py``.

Speed-up (plan 5.3): run multi-source Dijkstra from facilities and only recompute the
habitations whose shortest-path *tree* uses a failed edge. A habitation whose baseline
path is untouched cannot do worse (``tau^F >= tau^0``), so its delta is exactly zero.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import networkx as nx

WEIGHT_ATTR = "travel_time_min"
INF = math.inf


def _edge_key(u, v) -> frozenset:
    return frozenset((u, v))


def _multi_source_dijkstra(
    g: nx.Graph,
    sources: list,
    blocked_nodes: frozenset,
    blocked_edges: frozenset,
    weight: str = WEIGHT_ATTR,
):
    """Multi-source Dijkstra that skips blocked nodes/edges and records parents.

    Returns ``(dist, parent)`` where ``parent[n]`` is the predecessor node on the
    shortest path from the nearest source to ``n`` (``None`` for sources).
    """
    dist: dict = {}
    parent: dict = {}
    heap: list = []
    for s in sources:
        if s in blocked_nodes:
            continue
        if dist.get(s, INF) > 0.0:
            dist[s] = 0.0
            parent[s] = None
            heapq.heappush(heap, (0.0, s))
    while heap:
        d, n = heapq.heappop(heap)
        if d > dist.get(n, INF):
            continue
        for nb in g.neighbors(n):
            if nb in blocked_nodes:
                continue
            if _edge_key(n, nb) in blocked_edges:
                continue
            w = g.edges[n, nb].get(weight, 1.0)
            nd = d + w
            if nd < dist.get(nb, INF):
                dist[nb] = nd
                parent[nb] = n
                heapq.heappush(heap, (nd, nb))
    return dist, parent


@dataclass
class AccessibilityModel:
    """Reusable model; baseline travel times are computed once and cached.

    Parameters
    ----------
    graph:         road graph with ``travel_time_min`` on edges.
    habitations:   node id -> population.
    facilities:    facility type -> list of nodes (e.g. {"health": [...], "school": [...]}).
    caps_min:      facility type -> acceptable travel time cap T_k (minutes).
    weights:       facility type -> weight w_k (policy choice).
    weight_attr:   edge attribute holding travel time.
    """

    graph: nx.Graph
    habitations: dict
    facilities: dict[str, list]
    caps_min: dict[str, float]
    weights: dict[str, float]
    weight_attr: str = WEIGHT_ATTR

    _baseline_dist: dict[str, dict] = field(default_factory=dict, init=False)
    _baseline_parent: dict[str, dict] = field(default_factory=dict, init=False)
    _baseline_phi: dict[str, dict] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for k in self.facilities:
            if k not in self.caps_min:
                raise KeyError(f"missing cap T_k for facility type {k!r}")
            if k not in self.weights:
                raise KeyError(f"missing weight w_k for facility type {k!r}")
        self._compute_baseline()

    # -- helpers -------------------------------------------------------------------
    def _phi(self, tau: float, cap: float) -> float:
        if tau is None or tau == INF or tau >= cap:
            return 1.0
        return tau / cap

    def _compute_baseline(self) -> None:
        empty = frozenset()
        for k, srcs in self.facilities.items():
            dist, parent = _multi_source_dijkstra(
                self.graph, srcs, empty, empty, self.weight_attr
            )
            self._baseline_dist[k] = dist
            self._baseline_parent[k] = parent
            cap = self.caps_min[k]
            self._baseline_phi[k] = {
                h: self._phi(dist.get(h, INF), cap) for h in self.habitations
            }

    def baseline_times(self, k: str) -> dict:
        """tau^0_k(h) for every habitation (unreachable -> ``inf``)."""
        return {h: self._baseline_dist[k].get(h, INF) for h in self.habitations}

    def affected_habitations(self, k: str, failed_edges=(), failed_nodes=()) -> set:
        """Habitations whose baseline shortest-path tree uses a failed edge/node."""
        blocked_edges = frozenset(_edge_key(u, v) for u, v in failed_edges)
        blocked_nodes = frozenset(failed_nodes)
        parent = self._baseline_parent[k]
        affected = set()
        for h in self.habitations:
            if h in blocked_nodes:
                affected.add(h)
                continue
            n = h
            while parent.get(n) is not None:
                p = parent[n]
                if p in blocked_nodes or _edge_key(n, p) in blocked_edges:
                    affected.add(h)
                    break
                n = p
        return affected

    # -- loss ----------------------------------------------------------------------
    def loss(self, failed_edges=(), failed_nodes=(), validate: bool = False) -> float:
        """Person-minutes-style loss ``L(F)`` over the whole failure set.

        ``failed_nodes`` is how structure failures enter: a failed structure node is
        removed, which removes its incident edges.
        """
        failed_edges = tuple(failed_edges)
        failed_nodes = frozenset(failed_nodes)
        blocked_edges = frozenset(_edge_key(u, v) for u, v in failed_edges)

        if validate:
            for u, v in failed_edges:
                if not self.graph.has_edge(u, v):
                    raise KeyError(f"failed edge ({u}, {v}) not in graph")
            for n in failed_nodes:
                if n not in self.graph:
                    raise KeyError(f"failed node {n!r} not in graph")

        total = 0.0
        for k, srcs in self.facilities.items():
            cap = self.caps_min[k]
            w = self.weights[k]
            phi0 = self._baseline_phi[k]
            affected = self.affected_habitations(k, failed_edges, failed_nodes)
            if not affected:
                continue
            dist, _ = _multi_source_dijkstra(
                self.graph, srcs, failed_nodes, blocked_edges, self.weight_attr
            )
            for h in affected:
                tau_f = dist.get(h, INF)
                delta = self._phi(tau_f, cap) - phi0[h]
                if delta > 0.0:
                    total += self.habitations[h] * w * delta
        return total

    def societal_cost(self, outage_days: float, **kwargs) -> float:
        """``C(F) = D * L(F)``."""
        return outage_days * self.loss(**kwargs)
