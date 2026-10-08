"""Road-network build, snapping and QA (plan section 5.1).

The graph is a plain ``networkx.Graph`` for the prototype stage; the plan reserves
``python-igraph`` for the performance-critical shortest-path work (WP2/WP7). Edges carry
``length_m``, ``road_class``, ``speed_kph`` and the derived ``travel_time_min`` — the
single edge attribute the consequence model consumes.

Nodes carry ``pos = (x, y)`` and ``kind`` in {"junction", "habitation", "facility",
"structure"}. Habitations and facilities are *attached* to the road graph by snapping,
so a habitation node is a real node the travel-time model can start from.

Nothing here reads a real dataset yet; it operates on node/edge tables (synthetic
fixtures in tests, PMGSY/OSM later). Outputs are the contract, not the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

import networkx as nx
import numpy as np

RoadClass = Literal["rural", "state", "national"]
NodeKind = Literal["junction", "habitation", "facility", "structure"]

# Free-flow speeds are an assumption in the register (plan 5.1 step 3). These plain
# defaults mirror the register so the network module can stand alone in tests.
DEFAULT_CLASS_SPEEDS_KPH: dict[str, float] = {
    "rural": 30.0,
    "state": 50.0,
    "national": 70.0,
}

# Last-mile access to a snapped habitation/facility is on foot; this speed is an
# assumption (see the register). It converts the snap distance into a connector edge
# so assets are never floating nodes in separate components.
CONNECTOR_SPEED_KPH = 5.0


def class_speeds_from_register(register) -> dict[str, float]:
    """Pull the three class speeds out of an ``AssumptionRegister``."""
    return {
        "rural": register["speed_rural_kph"].default,
        "state": register["speed_state_kph"].default,
        "national": register["speed_national_kph"].default,
    }


def travel_time_minutes(length_m: float, speed_kph: float) -> float:
    """Minutes to traverse ``length_m`` at ``speed_kph``."""
    if length_m < 0:
        raise ValueError(f"negative length: {length_m}")
    if speed_kph <= 0:
        raise ValueError(f"non-positive speed: {speed_kph}")
    return (length_m / 1000.0) / speed_kph * 60.0


# --- construction -----------------------------------------------------------------


def new_graph() -> nx.Graph:
    return nx.Graph()


def add_junction(g: nx.Graph, node_id, x: float, y: float) -> None:
    g.add_node(node_id, pos=(float(x), float(y)), kind="junction")


def add_point(g: nx.Graph, node_id, x: float, y: float, kind: NodeKind) -> None:
    g.add_node(node_id, pos=(float(x), float(y)), kind=kind)


def add_road(
    g: nx.Graph,
    u,
    v,
    length_m: float,
    road_class: RoadClass,
    class_speeds: dict[str, float] | None = None,
) -> None:
    """Add an undirected road edge with derived travel time."""
    speeds = class_speeds or DEFAULT_CLASS_SPEEDS_KPH
    if road_class not in speeds:
        raise ValueError(f"unknown road_class {road_class!r}")
    speed = speeds[road_class]
    g.add_edge(
        u,
        v,
        length_m=float(length_m),
        road_class=road_class,
        speed_kph=float(speed),
        travel_time_min=travel_time_minutes(length_m, speed),
    )


def build_network(
    junctions: Iterable[tuple],
    roads: Iterable[tuple],
    class_speeds: dict[str, float] | None = None,
) -> nx.Graph:
    """Build a graph from ``(id, x, y)`` junctions and ``(u, v, length_m, class)`` roads."""
    speeds = class_speeds or DEFAULT_CLASS_SPEEDS_KPH
    g = new_graph()
    for node_id, x, y in junctions:
        add_junction(g, node_id, x, y)
    for u, v, length_m, road_class in roads:
        if u not in g or v not in g:
            raise KeyError(f"road ({u}, {v}) references an unknown junction")
        add_road(g, u, v, length_m, road_class, speeds)
    return g


# --- snapping ---------------------------------------------------------------------


@dataclass
class SnapResult:
    """Mapping from asset id -> attached graph node, plus the overshoot log."""

    attached: dict = field(default_factory=dict)
    overshot: dict = field(default_factory=dict)  # asset id -> distance beyond tolerance


def nearest_node_index(g: nx.Graph, nodes: list | None = None):
    """Return (node_ids, KDTree) over the given nodes (default: all nodes)."""
    from scipy.spatial import cKDTree

    ids = list(g.nodes) if nodes is None else list(nodes)
    coords = np.array([g.nodes[n]["pos"] for n in ids], dtype=float)
    return ids, cKDTree(coords)


def snap_points(
    g: nx.Graph,
    points: Iterable[tuple],
    tolerance_m: float = 25.0,
    node_pool: list | None = None,
    connector_speed_kph: float = CONNECTOR_SPEED_KPH,
) -> SnapResult:
    """Attach ``(asset_id, x, y, kind)`` points to the nearest node within tolerance.

    Each attached asset gets a **connector edge** to its host node (last-mile access,
    on foot), so it is routable. Points beyond tolerance are **not** attached and are
    logged as overshoots (plan 5.1 step 4: "log those beyond it"). Distance is planar
    metres; real builds will reproject to a metric CRS first.
    """
    ids, tree = nearest_node_index(g, node_pool)
    res = SnapResult()
    for asset_id, x, y, kind in points:
        dist, idx = tree.query([float(x), float(y)])
        node = ids[int(idx)]
        if dist <= tolerance_m:
            asset_node = f"{kind}:{asset_id}"
            g.add_node(asset_node, pos=(float(x), float(y)), kind=kind,
                       attached_to=node, snap_dist_m=float(dist))
            # connector edge: without it the asset is a floating node in its own
            # component and the consequence model cannot route from it.
            g.add_edge(
                asset_node,
                node,
                length_m=float(dist),
                road_class="connector",
                speed_kph=connector_speed_kph,
                travel_time_min=travel_time_minutes(float(dist), connector_speed_kph),
            )
            res.attached[asset_id] = asset_node
        else:
            res.overshot[asset_id] = float(dist)
    return res


# --- QA ---------------------------------------------------------------------------


@dataclass
class QAReport:
    n_nodes: int
    n_edges: int
    n_components: int
    largest_component_share: float
    n_habitations: int
    share_habitations_with_health: float
    n_facilities: int
    n_orphan_facilities: int
    min_health_reach: float
    passes: bool

    def to_markdown(self, district: str = "district") -> str:
        verdict = "PASS" if self.passes else "REJECT"
        return "\n".join(
            [
                f"# Network QA — {district}",
                "",
                f"- nodes: {self.n_nodes}",
                f"- edges: {self.n_edges}",
                f"- connected components: {self.n_components}",
                f"- share in largest component: {self.largest_component_share:.3f}",
                f"- habitations: {self.n_habitations}",
                f"- share of habitations reaching a health facility: "
                f"{self.share_habitations_with_health:.3f}",
                f"- health facilities: {self.n_facilities}",
                f"- orphan facilities (no path to any habitation): {self.n_orphan_facilities}",
                "",
                f"**Exit test (>={self.min_health_reach:.0%} habitations reach a health "
                f"facility): {verdict}**",
                "",
            ]
        )


def qa_report(
    g: nx.Graph,
    facility_nodes: dict[str, list],
    habitation_nodes: list,
    min_health_reach: float = 0.95,
) -> QAReport:
    """Components, connectivity and orphan diagnostics for the intact network."""
    comps = list(nx.connected_components(g))
    n_nodes = g.number_of_nodes()
    largest = max((len(c) for c in comps), default=0)

    health = list(facility_nodes.get("health", []))
    health_comps = {frozenset(c) for c in comps if any(f in c for f in health)}

    reachable = 0
    for h in habitation_nodes:
        if any(h in c for c in health_comps):
            reachable += 1
    share = reachable / len(habitation_nodes) if habitation_nodes else 0.0

    # orphan facility: a facility that shares no component with any habitation
    hab_comps = {frozenset(c) for c in comps if any(h in c for h in habitation_nodes)}
    n_orphan = 0
    for nodes in facility_nodes.values():
        for f in nodes:
            if not any(f in c for c in hab_comps):
                n_orphan += 1

    n_facilities = sum(len(v) for v in facility_nodes.values())

    return QAReport(
        n_nodes=n_nodes,
        n_edges=g.number_of_edges(),
        n_components=len(comps),
        largest_component_share=largest / n_nodes if n_nodes else 0.0,
        n_habitations=len(habitation_nodes),
        share_habitations_with_health=share,
        n_facilities=n_facilities,
        n_orphan_facilities=n_orphan,
        min_health_reach=min_health_reach,
        passes=share >= min_health_reach,
    )
