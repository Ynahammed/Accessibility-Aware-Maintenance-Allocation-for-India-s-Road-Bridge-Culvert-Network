"""Network-aware local search (plan section 5.7).

The additive MILP ignores non-additivity. This search starts from any feasible selection
(typically the MILP solution) and improves it with swap moves, evaluating the objective
on *sets* of assets. That objective may be the true sample-average accessibility loss,
which the MILP cannot express linearly — so no optimality guarantee is claimed; the plan
only asks for the gap to the exact additive solution on small instances (checked in the
tests) and a good solution on real ones.

Two neighbourhoods
------------------
* **single move** — change one asset's option.
* **pair move** — change two assets' options at once. This matters because the plan is
  budget-constrained: upgrading an asset usually needs budget freed elsewhere, and a
  single downgrade is never accepted on its own (it raises loss). Without pair moves the
  search stalls on any plan that spends its budget, which is exactly the failure E4
  surfaced (it lost to condition-first at redundancy 3–4).

Evaluations are memoised by selection, and ``feasible`` (optional) prunes candidates that
breach the budget or crew constraint before the expensive objective is computed.
"""

from __future__ import annotations

import numpy as np


def selection_to_x(sel, n_vars: int) -> np.ndarray:
    x = np.zeros(n_vars)
    x[np.asarray(sel, dtype=int)] = 1.0
    return x


def local_search(
    groups: list,
    sel,
    objective,
    n_vars: int | None = None,
    max_iter: int = 100,
    pair_moves: bool = True,
    feasible=None,
    memo: dict | None = None,
):
    """Swap-based hill climbing over one-asset and (optionally) two-asset moves.

    ``groups[a]`` lists the flat variable indices available to asset ``a`` (exactly one is
    chosen). ``objective(x)`` returns the value to minimise; ``feasible(sel)`` is an
    optional predicate on a flat selection list (budget/crew check). Returns
    ``(sel, value)``. ``memo`` may be shared across restarts to reuse evaluations.
    """
    sel = list(sel)
    if n_vars is None:
        n_vars = max(max(g) for g in groups) + 1
    values: dict = {} if memo is None else memo

    def value_of(trial) -> float:
        key = tuple(trial)
        if key not in values:
            values[key] = objective(selection_to_x(trial, n_vars))
        return values[key]

    cur = value_of(sel)
    for _ in range(max_iter):
        improved = False

        # -- single-asset moves ------------------------------------------------
        for a, group in enumerate(groups):
            best_var, best_val = sel[a], cur
            for var in group:
                if var == sel[a]:
                    continue
                trial = sel.copy()
                trial[a] = var
                if feasible is not None and not feasible(trial):
                    continue
                val = value_of(trial)
                if val < best_val - 1e-12:
                    best_val, best_var = val, var
            if best_var != sel[a]:
                sel[a], cur, improved = best_var, best_val, True

        # -- two-asset moves (budget-release trades) ---------------------------
        if pair_moves:
            best_pair = None
            best_pair_val = cur
            for a in range(len(groups)):
                for b in range(a + 1, len(groups)):
                    for va in groups[a]:
                        if va == sel[a]:
                            continue  # already covered by single moves
                        for vb in groups[b]:
                            if vb == sel[b]:
                                continue
                            trial = sel.copy()
                            trial[a], trial[b] = va, vb
                            if feasible is not None and not feasible(trial):
                                continue
                            val = value_of(trial)
                            if val < best_pair_val - 1e-12:
                                best_pair_val, best_pair = val, (a, b, va, vb)
            if best_pair is not None:
                a, b, va, vb = best_pair
                sel[a], sel[b] = va, vb
                cur, improved = best_pair_val, True

        if not improved:
            break
    return sel, cur


def greedy_construct(groups, objective, n_vars: int | None = None, feasible=None,
                     memo: dict | None = None):
    """Start from the first (usually do-nothing) option of every group and climb."""
    start = [g[0] for g in groups]
    return local_search(
        groups, start, objective, n_vars=n_vars, pair_moves=False, feasible=feasible,
        memo=memo,
    )


def multi_start_local_search(
    groups,
    starts,
    objective,
    n_vars: int | None = None,
    pair_moves: bool = True,
    feasible=None,
    max_iter: int = 100,
):
    """Refine every start and keep the best feasible selection.

    Feasible starts are refined with both move types; the returned selection is the best
    one seen. Evaluation memoisation is shared, so extra starts cost little.
    """
    memo: dict = {}
    best_sel, best_val = None, float("inf")
    for start in starts:
        if feasible is not None and not feasible(list(start)):
            continue
        sel, val = local_search(
            groups, start, objective, n_vars=n_vars, max_iter=max_iter,
            pair_moves=pair_moves, feasible=feasible, memo=memo,
        )
        if val < best_val:
            best_sel, best_val = sel, val
    if best_sel is None:  # no feasible start supplied: fall back to do-nothing
        best_sel = [g[0] for g in groups]
        best_val = objective(selection_to_x(best_sel, n_vars or (max(max(g) for g in groups) + 1)))
    return best_sel, best_val
