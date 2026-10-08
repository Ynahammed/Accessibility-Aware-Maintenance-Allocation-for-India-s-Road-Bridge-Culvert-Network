"""Synthetic district generator.

Real PMGSY/OSM/IMD downloads are the target, but the pipeline must be runnable and testable
without them. This builds a connected district graph with habitations, health/school
facilities and structures (bridges/culverts) at reproducible seeds, so E3-type comparisons
run end to end and every number is reproducible from a config.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from . import build
from .attach_assets import split_edge


@dataclass
class District:
    graph: nx.Graph
    habitations: dict = field(default_factory=dict)  # node -> population
    facilities: dict = field(default_factory=dict)  # type -> [node]
    structures: list = field(default_factory=list)  # (asset_id, node, structure_type)
    budget_crore: float = 100.0
    crew_days: float = 500.0


def make_district(
    n_junctions: int = 24,
    n_habitations: int = 14,
    n_structures: int = 10,
    seed: int = 0,
    spacing_m: float = 3000.0,
    class_speeds: dict | None = None,
) -> District:
    import numpy as np

    rng = np.random.default_rng(seed)
    speeds = class_speeds or build.DEFAULT_CLASS_SPEEDS_KPH
    # jittered grid so positions are roughly spread but not perfectly regular
    side = int(np.ceil(np.sqrt(n_junctions)))
    positions = []
    for i in range(n_junctions):
        r, c = divmod(i, side)
        x = c * spacing_m + rng.uniform(0, spacing_m * 0.4)
        y = r * spacing_m + rng.uniform(0, spacing_m * 0.4)
        positions.append((i, x, y))

    g = build.new_graph()
    for node_id, x, y in positions:
        build.add_junction(g, node_id, x, y)

    # spanning tree (guarantees connectivity) + a few chords (non-additivity)
    order = list(range(n_junctions))
    rng.shuffle(order)
    for i in range(1, n_junctions):
        u = order[i]
        v = order[rng.integers(0, i)]
        build.add_road(g, u, v, float(rng.uniform(800, 4000)), "rural", speeds)
    for _ in range(n_junctions // 3):
        u, v = int(rng.integers(0, n_junctions)), int(rng.integers(0, n_junctions))
        if u != v and not g.has_edge(u, v):
            build.add_road(g, u, v, float(rng.uniform(800, 4000)), "rural", speeds)

    # habitations and facilities sit on junctions (real builds snap PMGSY points)
    nodes = list(range(n_junctions))
    rng.shuffle(nodes)
    hab_nodes = nodes[:n_habitations]
    fac_nodes = nodes[n_habitations:n_habitations + 4]
    habitations = {}
    for h in hab_nodes:
        g.nodes[h]["kind"] = "habitation"
        habitations[h] = float(rng.integers(50, 800))
    facilities = {"health": [fac_nodes[0], fac_nodes[1]], "school": [fac_nodes[2], fac_nodes[3]]}
    for k, lst in facilities.items():
        for f in lst:
            g.nodes[f]["kind"] = "facility"
            g.nodes[f]["facility_type"] = k

    # structures split random edges
    edges = list(g.edges())
    rng.shuffle(edges)
    types = ["culvert", "minor_bridge", "major_bridge"]
    structures = []
    for i, (u, v) in enumerate(edges[:n_structures]):
        if not g.has_edge(u, v):
            continue
        frac = float(rng.uniform(0.25, 0.75))
        s_type = types[i % len(types)]
        node = split_edge(g, u, v, frac, f"S{i}", s_type)
        structures.append((f"S{i}", node, s_type))

    return District(
        graph=g,
        habitations=habitations,
        facilities=facilities,
        structures=structures,
        budget_crore=100.0,
        crew_days=500.0,
    )


def make_redundant_district(
    n_corridors: int = 3,
    redundancy: int = 2,
    seed: int = 0,
    population: float = 400.0,
    route_length_m: float = 1200.0,
    class_speeds: dict | None = None,
) -> District:
    """A district built to expose non-additivity (the E4 testbed).

    Each corridor is a habitation joined to the single facility by ``redundancy``
    **parallel** routes, each route carrying exactly one structure. Failing one structure
    is harmless (another route remains); failing *all* of them cuts the habitation off.
    Solo loss is therefore zero for every structure while the joint loss is large — the
    "two parallel routes cost zero alone and a lot together" case from plan 5.3.
    """
    speeds = class_speeds or build.DEFAULT_CLASS_SPEEDS_KPH
    g = build.new_graph()
    build.add_point(g, "F", 0.0, 0.0, "facility")
    g.nodes["F"]["facility_type"] = "health"

    habitations: dict = {}
    structures: list = []
    sid = 0
    for c in range(n_corridors):
        h = f"H{c}"
        build.add_point(g, h, 5000.0, 1500.0 * c, "habitation")
        habitations[h] = population
        for i in range(redundancy):
            j = f"H{c}_j{i}"
            build.add_point(g, j, 2500.0, 1500.0 * c + 30.0 * i, "junction")
            build.add_road(g, h, j, route_length_m, "rural", speeds)
            build.add_road(g, j, "F", route_length_m, "rural", speeds)
            node = split_edge(g, j, "F", 0.5, f"S{sid}", "culvert")
            structures.append((f"S{sid}", node, "culvert"))
            sid += 1

    return District(
        graph=g,
        habitations=habitations,
        facilities={"health": ["F"]},
        structures=structures,
        budget_crore=1.0,
        crew_days=200.0,
    )
