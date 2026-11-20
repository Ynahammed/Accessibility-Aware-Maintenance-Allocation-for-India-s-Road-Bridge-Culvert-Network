"""Coverage candidates for the network-aware search.

On a redundant corridor every structure protects nothing on its own: the habitation is
cut off only when *all* parallel routes fail. The additive MILP therefore sees zero
benefit everywhere and starts from do-nothing, and random restarts rarely happen to fund
a complete corridor. The search needs at least one start that covers a whole cut set.

This module finds those sets on the actual routing graph: the smallest set of structure
nodes whose simultaneous removal disconnects a habitation from every facility. That is a
minimum node cut restricted to structures, computed with a node-split max-flow so ordinary
road junctions cannot be counted as cuts.

A habitation can have several disjoint minimum cuts (alternative corridors). The max-flow
routine returns one at a time, so after finding a cut its structures are removed and the
search repeats: the result is a family of alternative cut sets for that habitation, not
just the first one. Each set carries the population it protects, so a plan covering a
thickly populated corridor is preferred to one covering a handful of people.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass

import networkx as nx

# Capacity for anything that is not a structure: large enough that a minimum cut never
# chooses it, small enough to stay exact in integer arithmetic.
_UNCUTTABLE = 10**9

# Cut sets depend only on the routing graph and on where the structures, habitations and
# facilities sit — not on condition, prices or scenario draws. The cache is keyed by the
# graph object (weakly, so it disappears with the graph) and by those node sets, so a new
# policy instance, a new request or a solver restart on the same topology reuses the
# max-flow result instead of recomputing one cut per habitation.
_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class CutSet:
    """One minimum structure cut and the population it would cut off."""

    assets: frozenset
    weight: float


def _cache_key(acc, node_of: dict) -> tuple:
    return (
        # cheap guard against an in-place edge/node change on a reused graph object
        (acc.graph.number_of_nodes(), acc.graph.number_of_edges()),
        tuple(sorted(node_of.items(), key=lambda item: str(item[0]))),
        tuple(sorted(acc.habitations.items(), key=lambda item: str(item[0]))),
        frozenset(
            (kind, node)
            for kind, nodes in acc.facilities.items()
            for node in nodes
        ),
    )


def _flow_network(graph, structures, facility_nodes, protected=()):
    """Node-split max-flow network; protected structures cannot be cut.

    A protected structure is treated as an ordinary node, so flow passes through it for
    free. Protecting one member of a found cut and recomputing is how alternative minimum
    cuts are enumerated without disconnecting the habitation.
    """
    protected = set(protected)
    cuttable = structures - protected

    flow = nx.DiGraph()
    for s in cuttable:
        flow.add_edge((s, "in"), (s, "out"), capacity=1)

    def in_node(n):
        return (n, "in") if n in cuttable else n

    def out_node(n):
        return (n, "out") if n in cuttable else n

    for u, v in graph.edges():
        flow.add_edge(out_node(u), in_node(v), capacity=_UNCUTTABLE)
        flow.add_edge(out_node(v), in_node(u), capacity=_UNCUTTABLE)

    # a unique object, not a string, so a graph node can never collide with the source
    source = object()
    flow.add_node(source)
    for f in facility_nodes:
        if f in graph:
            flow.add_edge(source, in_node(f), capacity=_UNCUTTABLE)
    return flow, source


def corridor_cut_sets(acc, assets, max_cuts_per_habitation: int = 6) -> list[CutSet]:
    """Minimum structure cut sets separating habitations from facilities.

    ``acc`` is an ``AccessibilityModel`` (graph, habitations, facilities); ``assets`` are
    simulator assets, whose ``node`` is the structure's graph node. Returns one ``CutSet``
    per distinct cut, ordered deterministically by size and asset ids. A corridor with
    three parallel routes yields one set with its three structures: repairing all of them
    is what removes the joint failure, and repairing any two of them is not.

    Where a habitation has alternative minimum cuts, they are enumerated by protecting one
    member of each cut found and recomputing (bounded by ``max_cuts_per_habitation`` and a
    flow-call budget). This finds series bottlenecks and alternative corridors; it does not
    promise every minimum cut in a densely meshed graph.

    Results are cached per ``(graph, structure nodes, habitations, facilities)``; callers
    that pass the same topology again skip the max-flow work entirely. The graph is held
    weakly, so the entry disappears with the model that owns it.
    """
    graph = acc.graph
    node_of = {a.asset_id: a.node for a in assets}
    structures = {n for n in node_of.values() if n in graph}
    if not structures:
        return []

    key = _cache_key(acc, node_of)
    per_graph = _CACHE.get(graph)
    if per_graph is None:
        per_graph = {}
        _CACHE[graph] = per_graph
    if key in per_graph:
        return list(per_graph[key])

    facility_nodes = {f for nodes in acc.facilities.values() for f in nodes}
    weights: dict[frozenset, float] = {}
    limit = max(1, int(max_cuts_per_habitation))
    for habitation, population in acc.habitations.items():
        if habitation not in graph or habitation in facility_nodes:
            continue

        def find_cut(protected):
            flow, source = _flow_network(graph, structures, facility_nodes, protected)
            if habitation not in flow or not nx.has_path(flow, source, habitation):
                return None, None
            try:
                value, (reachable, _) = nx.minimum_cut(
                    flow, source, habitation, capacity="capacity"
                )
            except nx.NetworkXError:  # pragma: no cover - defensive
                return None, None
            if value >= _UNCUTTABLE:  # no structure cut exists
                return None, None
            cut = frozenset(
                asset_id
                for asset_id, node in node_of.items()
                if node not in protected
                and (node, "in") in reachable
                and (node, "out") not in reachable
            )
            return value, cut or None

        min_value, first = find_cut(frozenset())
        if first is None:
            continue
        found: set[frozenset] = {first}
        queue = [frozenset({asset}) for asset in first]
        seen_forced = set(queue)
        calls = 1
        while queue and len(found) < limit and calls < 8 * limit:
            forced = queue.pop(0)
            value, cut = find_cut(forced)
            calls += 1
            if cut is None or value != min_value:
                continue  # protecting a cut member cannot lower the cut size
            found.add(cut)
            for asset in cut:
                branch = forced | {asset}
                if branch not in seen_forced:
                    seen_forced.add(branch)
                    queue.append(branch)

        for cut in found:
            weights[cut] = weights.get(cut, 0.0) + float(population)

    cuts = [
        CutSet(assets=cut, weight=weight)
        for cut, weight in sorted(
            weights.items(), key=lambda item: (len(item[0]), sorted(item[0]))
        )
    ]
    per_graph[key] = tuple(cuts)
    return list(cuts)
