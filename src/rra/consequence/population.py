"""Population allocation (plan 5.3).

Prefer PMGSY habitation population where present; otherwise allocate a gridded
population raster to the nearest habitation. This is the fallback path.
"""

from __future__ import annotations

import numpy as np


def allocate_population_to_habitations(
    cells: list[tuple],
    habitation_nodes: list,
    pos_of,
) -> dict:
    """Assign each ``(x, y, population)`` cell to its nearest habitation node.

    ``pos_of(node)`` returns ``(x, y)`` for a habitation node id.
    Returns node id -> summed population. Cells with no habitation are dropped.
    """
    from scipy.spatial import cKDTree

    if not habitation_nodes:
        return {}
    coords = np.array([pos_of(n) for n in habitation_nodes], dtype=float)
    tree = cKDTree(coords)
    out: dict = {n: 0.0 for n in habitation_nodes}
    for x, y, pop in cells:
        _, idx = tree.query([float(x), float(y)])
        out[habitation_nodes[int(idx)]] += float(pop)
    return out
