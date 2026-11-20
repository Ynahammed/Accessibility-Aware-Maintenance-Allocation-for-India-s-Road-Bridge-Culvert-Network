"""Optimizer-backed policies (plan section 5.7): additive MILP and network-aware search.

Both plan one year at a time from the current world state, under a fixed sample of
rainfall ratios (the uncertainty the optimizer sees this year). The additive policy is the
MILP optimum of the linearised problem; the network-aware policy warm-starts from it and
improves with swap-based local search on the true set-based loss, falling back to the MILP
plan if a move would breach budget or crew.
"""

from __future__ import annotations

import numpy as np

from rra.cost.interventions import COST_MULTIPLIER, Intervention
from rra.optimize.coverage import corridor_cut_sets
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


def _coverage_rank(scored, cuts, index) -> list:
    """Pick the best candidate: protected population first, then loss, then spend.

    ``scored`` holds ``(validation_loss, spend, selection)``. The validation sample is a
    rare-event estimator, so a partial plan can appear better by sampling noise. Repairing
    an extra structure cannot make the true expected loss worse, so coverage is the
    reliable signal and is ranked ahead of the noisy loss rather than used as a tie-break.
    Cut sets are weighted by the population they protect, so a plan covering a large
    corridor is preferred to one covering a handful of people.
    """

    def uncovered(sel) -> float:
        return sum(
            cut.weight
            for cut in cuts
            if any(sel[index[a]] % N_OPTIONS == 0 for a in cut.assets if a in index)
        )

    return min(scored, key=lambda item: (uncovered(item[2]), item[0], item[1]))[2]


def _improving_levels(models) -> list[int]:
    """Intervention levels that are not dominated by a cheaper level with a larger reset.

    A dominated level can never be the right choice for an asset, so a start that applies
    it uniformly is dominated too. On the reply register, for example, a major repair costs
    4x a minor one and resets the same two steps, so only minor and replace are offered.
    """
    levels = []
    for option in range(1, N_OPTIONS):
        intervention = OPTION_LIST[option]
        levels.append(
            (
                option,
                models.effect(intervention).condition_reset,
                COST_MULTIPLIER[intervention.value],
            )
        )
    return [
        option
        for option, reset, cost in levels
        if not any(
            other_reset >= reset
            and other_cost <= cost
            and (other_reset > reset or other_cost < cost)
            for other, other_reset, other_cost in levels
            if other != option
        )
    ]


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


class FixedPlanPolicy:
    """Replay a pre-computed multi-year plan, one simulated year at a time.

    The plan comes from :mod:`rra.optimize.multiperiod`, which may spend less than the
    annual budget in year 0 and carries the remainder forward. The policy is therefore
    stateless but budget-aware: in a later year it allows the saved deployment plus what
    the earlier years left unspent, computed from the plan itself. A stateful ledger would
    leak between scenarios, because the simulator reuses one policy object across draws.
    """

    def __init__(self, plans_by_year: dict, name: str = "fixed_plan"):
        self.plans_by_year = {int(k): dict(v) for k, v in plans_by_year.items()}
        self.name = name

    def _available(self, year: int, assets, sor, annual: float) -> float:
        """Annual budget plus unspent earlier years, in crore."""
        types = {a.asset_id: a.structure_type for a in assets}
        spent = 0.0
        for y in range(year):
            for asset_id, opt in self.plans_by_year.get(y, {}).items():
                if asset_id in types:
                    spent += sor.cost(types[asset_id], opt)
        return annual * (year + 1) - spent

    def propose(self, assets, ctx) -> dict:
        annual = float(ctx.budget_crore)
        year = int(getattr(ctx, "year", 0))
        plan = self.plans_by_year.get(year, {})
        # no per-year cap: the schedule was solved with a two-year total of twice the annual
        # budget, so a later year may legitimately spend what an earlier year saved. The
        # running total is the only thing that has to hold.
        available = self._available(year, assets, ctx.sor, annual)
        used_crew = 0.0
        chosen: dict = {}
        types = {a.asset_id: a.structure_type for a in assets}
        spent = 0.0
        for asset_id, opt in plan.items():
            if asset_id not in types:
                continue
            cost = ctx.sor.cost(types[asset_id], opt)
            crew = ctx.sor.labour(types[asset_id], opt)
            if spent + cost <= available + 1e-9 and used_crew + crew <= ctx.crew_days + 1e-9:
                chosen[asset_id] = opt
                spent += cost
                used_crew += crew
        return chosen


class NetworkAwarePolicy(AdditiveMilpPolicy):
    """Set-based local search with two-asset moves and restarts (plan 5.7).

    Starts: the additive MILP plan, the do-nothing plan, a **corridor-coverage** plan for
    every minimum structure cut set (one structure per parallel route, so the cut is
    complete), and ``restarts`` seeded random-but-feasible plans. The coverage starts are
    what make the search see joint failure at all: on a redundant corridor every asset's
    solo loss is zero, so the MILP funds nothing and random restarts rarely complete a
    corridor. Two-asset moves let it free budget on one asset to fund a better repair
    elsewhere — the plan's flagged failure mode of a budget-binding single-move search.

    Selection: the sample-average surrogate is a **rare-event** estimator — loss needs a
    whole parallel corridor to fail — so on a small fit sample a plan can score exactly
    zero by spending its budget where the sampled rains were worst, then generalise badly
    (measured in E4 at redundancy 4). Candidate plans are therefore ranked on an
    independent validation sample drawn from the same rainfall distribution before one is
    returned. Coverage is ranked ahead of that loss, because a partial corridor can look
    better on a rare-event sample but cannot be better in expectation. Optimise on the fit
    sample, *select* out of sample.
    """

    name = "network_aware"

    def __init__(self, models, rain_samples, seed: int = 0, lam: float = 0.0,
                 alpha: float = 0.05, pair_moves: bool = True, restarts: int = 1,
                 validation_samples: int = 240):
        super().__init__(models, rain_samples, seed=seed, lam=lam, alpha=alpha)
        self.seed = int(seed)
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

    def _coverage_starts(self, assets, inst, feasible, cuts) -> list:
        """Starts that fund whole minimum cut sets, at each intervention level.

        A cut set is funded whole: covering part of a corridor leaves the habitation one
        failure away from being cut off, which is what the additive objective cannot see.
        Both each single cut set and the union of all of them are offered, so the search
        contains the plan that protects every corridor rather than only one at a time.
        Levels are the non-dominated intervention options; the validation sample decides
        among them.
        """
        index = {a.asset_id: i for i, a in enumerate(assets)}
        weighted = [
            (cut.weight, [index[a] for a in cut.assets if a in index]) for cut in cuts
        ]
        weighted = [(w, members) for w, members in weighted if members]
        weighted.sort(key=lambda item: (-item[0], len(item[1])))
        groups = [members for _, members in weighted]
        groups.append(sorted({i for g in groups for i in g}))  # all corridors together

        out: list = []
        seen: set = set()

        def add(sel) -> None:
            key = tuple(sel)
            if key in seen or not feasible(sel):
                return
            seen.add(key)
            out.append(sel)

        for option in _improving_levels(self.models):
            base = [i * N_OPTIONS for i in range(len(assets))]
            for members in groups:
                sel = base.copy()
                for i in members:
                    sel[i] = i * N_OPTIONS + option
                add(sel)

            # as many whole cut sets as the budget fits, adding the most populated first:
            # a single cut set and the full union do not span the budgets in between
            sel = base.copy()
            for _, members in weighted:
                trial = sel.copy()
                for i in members:
                    trial[i] = i * N_OPTIONS + option
                if feasible(trial):
                    sel = trial
                    add(sel)
        return out

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
        cuts = corridor_cut_sets(self.models.acc, assets)
        index = {a.asset_id: i for i, a in enumerate(assets)}
        starts = [milp_sel, none_sel]
        starts.extend(self._coverage_starts(assets, inst, feasible, cuts))
        rng = np.random.default_rng(self.seed + na * 7919 + len(assets))
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
                scored = [
                    (
                        validation(selection_to_x(s, inst.n_vars)),
                        float(sum(inst.cost[v] for v in s)),
                        s,
                    )
                    for s in candidates
                ]
                sel = _coverage_rank(scored, cuts, index)

        # never hand back a plan that breaches budget or crew
        if not feasible(sel):
            sel = milp_sel if feasible(milp_sel) else none_sel
        opt_index = [v - i * N_OPTIONS for i, v in enumerate(sel)]
        return _to_interventions(assets, opt_index)
