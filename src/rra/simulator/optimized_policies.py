"""Optimizer-backed policies (plan section 5.7): additive MILP and network-aware search.

Both plan one year at a time from the current world state, under a fixed sample of
rainfall ratios (the uncertainty the optimizer sees this year). The additive policy is the
MILP optimum of the linearised problem; the network-aware policy warm-starts from it and
improves with swap-based local search on the true set-based loss, falling back to the MILP
plan if a move would breach budget or crew.
"""

from __future__ import annotations

import numpy as np

from rra.cost.interventions import Intervention
from rra.optimize.instance import (
    N_OPTIONS,
    OPTION_LIST,
    build_additive_instance,
    network_aware_objective,
)
from rra.optimize.local_search import local_search
from rra.optimize.milp import solve_additive


def _selection(x, n_assets: int) -> list:
    return [int(np.argmax(x[i * N_OPTIONS:(i + 1) * N_OPTIONS])) for i in range(n_assets)]


def _to_interventions(assets, sel) -> dict:
    out = {}
    for i, a in enumerate(assets):
        opt = OPTION_LIST[sel[i]]
        if opt is not Intervention.NONE:
            out[a.asset_id] = opt
    return out


class AdditiveMilpPolicy:
    name = "additive_milp"

    def __init__(self, models, rain_samples, seed: int = 0, lam: float = 0.0, alpha: float = 0.05):
        self.models = models
        self.rain = np.asarray(rain_samples, dtype=float)  # (S, n_assets)
        self.lam = lam
        self.alpha = alpha
        rng = np.random.default_rng(seed)
        self.crn_u = rng.random((self.rain.shape[1], self.rain.shape[0]))  # (n_assets, S)

    def propose(self, assets, ctx) -> dict:
        assets = list(assets)
        inst = build_additive_instance(assets, self.models, self.rain)
        x, _, _ = solve_additive(inst, ctx.budget_crore, ctx.crew_days, self.lam, self.alpha)
        return _to_interventions(assets, _selection(x, len(assets)))


class NetworkAwarePolicy(AdditiveMilpPolicy):
    name = "network_aware"

    def propose(self, assets, ctx) -> dict:
        assets = list(assets)
        na = len(assets)
        inst = build_additive_instance(assets, self.models, self.rain)
        x0, _, _ = solve_additive(inst, ctx.budget_crore, ctx.crew_days, self.lam, self.alpha)
        # flat variable indices (i * N_OPTIONS + option) expected by local_search
        sel0 = [i * N_OPTIONS + _selection(x0, na)[i] for i in range(na)]

        objective = network_aware_objective(
            assets, self.models, self.rain, self.crn_u, ctx.budget_crore, ctx.crew_days
        )
        sel, _ = local_search(inst.asset_groups, sel0, objective, n_vars=inst.n_vars)

        # keep the MILP plan if local search breached a constraint
        spent = float(sum(inst.cost[v] for v in sel))
        used = float(sum(inst.labour[v] for v in sel))
        if spent > ctx.budget_crore + 1e-6 or used > ctx.crew_days + 1e-6:
            sel = sel0
        opt_index = [v - i * N_OPTIONS for i, v in enumerate(sel)]
        return _to_interventions(assets, opt_index)
