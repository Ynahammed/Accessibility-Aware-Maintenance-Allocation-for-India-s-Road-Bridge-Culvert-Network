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
from rra.optimize.local_search import multi_start_local_search, selection_to_x
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
    """Set-based local search with two-asset moves and restarts (plan 5.7).

    Starts: the additive MILP plan, the do-nothing plan, and ``restarts`` seeded
    random-but-feasible plans, so the search is not trapped by a MILP that cannot see
    joint failure. Two-asset moves let it free budget on one asset to fund a better
    repair elsewhere — the plan's flagged failure mode of a budget-binding single-move
    search.

    Selection: the sample-average surrogate is a **rare-event** estimator — loss needs a
    whole parallel corridor to fail — so on a small fit sample a plan can score exactly
    zero by spending its budget where the sampled rains were worst, then generalise badly
    (measured in E4 at redundancy 4). Candidate plans are therefore ranked on an
    independent validation sample drawn from the same rainfall distribution before one is
    returned. Optimise on the fit sample, *select* out of sample.
    """

    name = "network_aware"

    def __init__(self, models, rain_samples, seed: int = 0, lam: float = 0.0,
                 alpha: float = 0.05, pair_moves: bool = True, restarts: int = 1,
                 validation_samples: int = 240):
        super().__init__(models, rain_samples, seed=seed, lam=lam, alpha=alpha)
        self.pair_moves = pair_moves
        self.restarts = int(restarts)
        self.validation_samples = int(validation_samples)
        if self.validation_samples > 0:
            rng = np.random.default_rng(seed + 31337)
            n_assets = self.rain.shape[1]
            flat = self.rain.reshape(-1)
            # bootstrap the supplied rainfall distribution, jittered so validation draws
            # are not exact repeats of the fit draws
            size = (self.validation_samples, n_assets)
            self.val_rain = rng.choice(flat, size=size, replace=True) * np.exp(
                rng.normal(0.0, 0.05, size=size)
            )
            self.val_u = rng.random((n_assets, self.validation_samples))

    def _random_feasible_start(self, rng, groups, cost, labour, budget, crew):
        """Greedy random insertion of repairs into an all-NONE plan."""
        sel = [g[0] for g in groups]
        spent, used = 0.0, 0.0
        for a in rng.permutation(len(groups)):
            opt = int(rng.integers(1, len(groups[a])))
            v = groups[a][opt]
            if spent + cost[v] <= budget and used + labour[v] <= crew:
                sel[a] = v
                spent += cost[v]
                used += labour[v]
        return sel

    def propose(self, assets, ctx) -> dict:
        assets = list(assets)
        na = len(assets)
        inst = build_additive_instance(assets, self.models, self.rain)
        x0, _, _ = solve_additive(inst, ctx.budget_crore, ctx.crew_days, self.lam, self.alpha)
        # flat variable indices (i * N_OPTIONS + option) expected by local_search
        milp_sel = [i * N_OPTIONS + _selection(x0, na)[i] for i in range(na)]
        none_sel = [i * N_OPTIONS for i in range(na)]
        cost = {v: float(inst.cost[v]) for v in range(inst.n_vars)}
        labour = {v: float(inst.labour[v]) for v in range(inst.n_vars)}

        def feasible(sel) -> bool:
            return (
                sum(cost[v] for v in sel) <= ctx.budget_crore + 1e-9
                and sum(labour[v] for v in sel) <= ctx.crew_days + 1e-9
            )

        objective = network_aware_objective(
            assets, self.models, self.rain, self.crn_u, ctx.budget_crore, ctx.crew_days
        )
        starts = [milp_sel, none_sel]
        rng = np.random.default_rng(na * 7919 + len(assets))
        for _ in range(self.restarts):
            starts.append(
                self._random_feasible_start(
                    rng, inst.asset_groups, cost, labour, ctx.budget_crore, ctx.crew_days
                )
            )
        sel, _ = multi_start_local_search(
            inst.asset_groups, starts, objective,
            n_vars=inst.n_vars, pair_moves=self.pair_moves, feasible=feasible,
        )

        # select among candidates on a fresh sample (rare-event surrogate guard)
        if self.validation_samples > 0:
            validation = network_aware_objective(
                assets, self.models, self.val_rain, self.val_u, ctx.budget_crore, ctx.crew_days
            )
            candidates = [s for s in [sel] + starts if feasible(s)]
            if candidates:
                sel = min(
                    candidates,
                    key=lambda s: validation(selection_to_x(s, inst.n_vars)),
                )

        # never hand back a plan that breaches budget or crew
        if not feasible(sel):
            sel = milp_sel if feasible(milp_sel) else none_sel
        opt_index = [v - i * N_OPTIONS for i, v in enumerate(sel)]
        return _to_interventions(assets, opt_index)
