"""Network-aware local search (plan section 5.7).

The additive MILP ignores non-additivity. This search starts from any feasible selection
(typically the MILP solution) and improves it with swap moves, evaluating the objective
on *sets* of assets. That objective may be the true sample-average accessibility loss,
which the MILP cannot express linearly — so no optimality guarantee is claimed; the plan
only asks for the gap to the exact additive solution on small instances (checked in the
tests) and a good solution on real ones.
"""

from __future__ import annotations

import numpy as np


def selection_to_x(sel, n_vars: int) -> np.ndarray:
    x = np.zeros(n_vars)
    x[np.asarray(sel, dtype=int)] = 1.0
    return x


def local_search(groups: list, sel, objective, n_vars: int | None = None, max_iter: int = 100):
    """Swap-based hill climbing.

    ``groups[a]`` lists the flat variable indices available to asset ``a`` (exactly one is
    chosen). ``objective(x)`` returns the value to minimise. Returns ``(sel, value)``.
    """
    sel = list(sel)
    if n_vars is None:
        n_vars = max(max(g) for g in groups) + 1
    cur = objective(selection_to_x(sel, n_vars))
    for _ in range(max_iter):
        improved = False
        for a, group in enumerate(groups):
            best_var, best_val = sel[a], cur
            for var in group:
                if var == sel[a]:
                    continue
                trial = sel.copy()
                trial[a] = var
                val = objective(selection_to_x(trial, n_vars))
                if val < best_val - 1e-12:
                    best_val, best_var = val, var
            if best_var != sel[a]:
                sel[a], cur, improved = best_var, best_val, True
        if not improved:
            break
    return sel, cur
