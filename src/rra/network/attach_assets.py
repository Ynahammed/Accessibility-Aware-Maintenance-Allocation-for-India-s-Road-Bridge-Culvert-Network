"""Attach bridge/culvert structures to the graph by splitting edges (plan 5.1 step 5).

A structure that sits inside a road segment becomes its own node so that *failing that
structure* is equivalent to *removing that node's incident edges* in the consequence
model. Splitting preserves road class and speed and divides length proportionally, so
total travel time on the intact network is unchanged.
"""

from __future__ import annotations

import networkx as nx


def split_edge(
    g: nx.Graph,
    u,
    v,
    fraction: float,
    structure_id,
    structure_type: str = "culvert",
) -> str:
    """Split edge (u, v) at ``fraction`` (0..1 from u) with a new structure node.

    Returns the new node id. Travel time is conserved: the two halves sum to the original.
    """
    if not g.has_edge(u, v):
        raise KeyError(f"no edge ({u}, {v})")
    if not 0.0 < fraction < 1.0:
        raise ValueError(f"fraction must be in (0, 1), got {fraction}")

    data = g.edges[u, v]
    length = data["length_m"]
    node_id = f"structure:{structure_id}"

    ux, uy = g.nodes[u]["pos"]
    vx, vy = g.nodes[v]["pos"]
    x = ux + (vx - ux) * fraction
    y = uy + (vy - uy) * fraction

    g.add_node(
        node_id,
        pos=(x, y),
        kind="structure",
        structure_type=structure_type,
        on_edge=(u, v),
        fraction=fraction,
    )

    # preserve edge attributes, split length by fraction, recolour the two halves
    g.remove_edge(u, v)
    for (a, b), frac in (((u, node_id), fraction), ((node_id, v), 1.0 - fraction)):
        new_data = dict(data)
        new_data["length_m"] = length * frac
        new_data["travel_time_min"] = data["travel_time_min"] * frac
        g.add_edge(a, b, **new_data)

    return node_id


def attach_structures(
    g: nx.Graph,
    structures: list[tuple],
) -> dict:
    """Split edges for each ``(structure_id, u, v, fraction, structure_type)`` entry.

    Returns a mapping structure_id -> node id. Structures sharing an edge are applied
    in the order given; callers should supply them sorted along the edge.
    """
    attached: dict = {}
    for structure_id, u, v, fraction, s_type in structures:
        node_id = split_edge(g, u, v, fraction, structure_id, s_type)
        attached[structure_id] = node_id
    return attached
