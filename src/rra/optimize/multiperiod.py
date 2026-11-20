"""Two-period additive maintenance scheduling with budget carryover.

The year-1 plan in E9 is a *receding-horizon* plan: the simulator re-solves the additive
MILP every year on the state it actually reached, with a fresh one-year budget. That is not
a scheduling model. It cannot decide to postpone work, and unspent money does not follow it
into the next year.

This module adds the smallest model that can test those two things on the same 30 assets:

* **paths.** Each asset has 16 two-year paths ``(option_year0, option_year1)``. A path
  carries its cost and crew-days per year and the condition it reaches, so "exactly one
  path per asset" keeps the problem linear while letting year 1 depend on year 2.
* **carryover.** Year-0 spend is capped by the annual budget, and the two-year total by
  twice the annual budget — i.e. unspent year-0 money is available in year 1.
* **deterioration.** Between the two years the condition moves to its *expected* next
  state under the fitted transition matrix. That is a deterministic approximation of a
  stochastic process; it is stated as such rather than hidden.

The objective is the expected accessibility loss over both years under the optimizer's
rainfall sample. Emergency repairs, failures and the joint network response are absent from
the model and are supplied by the simulator when its plan is replayed, which is why the
plan is always evaluated there rather than trusted from the MILP objective.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from rra.cost.interventions import apply_effect
from rra.fragility.fragility import failure_probability

from .instance import N_OPTIONS, OPTION_LIST


@dataclass
class MultiPeriodPlan:
    """A two-year schedule, its declared objective, and the assumptions behind it."""

    year0: dict
    year1: dict
    objective: float
    spend_year0: float
    spend_total: float
    n_paths: int
    note: str

    def as_dict(self) -> dict:
        return {
            "year0": self.year0,
            "year1": self.year1,
            "objective": self.objective,
            "spend_year0_crore": self.spend_year0,
            "spend_total_crore": self.spend_total,
            "n_paths": self.n_paths,
            "note": self.note,
        }


def _expected_next_state(condition: int, transition: np.ndarray) -> int:
    """Rounded expectation of the next condition state (deterministic approximation)."""
    states = np.arange(transition.shape[1], dtype=float)
    mean = float(np.asarray(transition)[int(condition)] @ states)
    return int(np.clip(np.rint(mean), 0, transition.shape[1] - 1))


def solve_multiperiod(
    assets,
    models,
    rain_samples,
    budget: float,
    crew: float,
    solo: dict | None = None,
) -> MultiPeriodPlan:
    """Solve the two-period schedule and return both years' intervention choices."""
    from .instance import solo_losses

    assets = list(assets)
    na = len(assets)
    solo = dict(solo) if solo is not None else solo_losses(assets, models)
    rain = np.asarray(rain_samples, dtype=float)
    mean_rain = rain.mean(axis=0) if rain.ndim == 2 else np.full(na, float(rain))

    paths = []  # (asset_index, j0, j1)
    for i, a in enumerate(assets):
        for j0 in range(N_OPTIONS):
            e0 = models.effect(OPTION_LIST[j0])
            cond0 = apply_effect(a.condition, e0)
            cond_det = _expected_next_state(cond0, models.transition)
            for j1 in range(N_OPTIONS):
                e1 = models.effect(OPTION_LIST[j1])
                cond1 = apply_effect(cond_det, e1)
                paths.append((i, j0, j1, cond0, cond1, e0.fragility_factor, e1.fragility_factor))

    n = len(paths)
    cost0 = np.zeros(n)
    cost1 = np.zeros(n)
    lab0 = np.zeros(n)
    lab1 = np.zeros(n)
    loss = np.zeros(n)
    for v, (i, j0, j1, cond0, cond1, f0, f1) in enumerate(paths):
        a = assets[i]
        cost0[v] = models.sor.cost(a.structure_type, OPTION_LIST[j0])
        cost1[v] = models.sor.cost(a.structure_type, OPTION_LIST[j1])
        lab0[v] = models.sor.labour(a.structure_type, OPTION_LIST[j0])
        lab1[v] = models.sor.labour(a.structure_type, OPTION_LIST[j1])
        outage = models.outage(a)
        p0 = failure_probability(int(cond0), float(max(mean_rain[i], 1e-9)), models.fragility) * f0
        p1 = failure_probability(int(cond1), float(max(mean_rain[i], 1e-9)), models.fragility) * f1
        loss[v] = (p0 + p1) * outage * float(solo.get(a.asset_id, 0.0))

    rows, lb, ub = [], [], []
    row = np.zeros(n); row[:] = cost0
    rows.append(row); lb.append(-np.inf); ub.append(budget)
    row = np.zeros(n); row[:] = cost0 + cost1
    rows.append(row); lb.append(-np.inf); ub.append(2.0 * budget)
    row = np.zeros(n); row[:] = lab0
    rows.append(row); lb.append(-np.inf); ub.append(crew)
    row = np.zeros(n); row[:] = lab0 + lab1
    rows.append(row); lb.append(-np.inf); ub.append(2.0 * crew)
    for i in range(na):
        row = np.zeros(n)
        row[[v for v, p in enumerate(paths) if p[0] == i]] = 1.0
        rows.append(row); lb.append(1.0); ub.append(1.0)

    res = milp(
        c=loss,
        constraints=LinearConstraint(np.vstack(rows), np.array(lb), np.array(ub)),
        integrality=np.ones(n, dtype=int),
        bounds=Bounds(np.zeros(n), np.ones(n)),
    )
    if res.x is None:  # pragma: no cover - the all-NONE path is always feasible
        raise RuntimeError(f"multi-period MILP failed: {res.message}")
    chosen = np.flatnonzero(np.round(res.x).astype(int))
    year0: dict = {}
    year1: dict = {}
    for v in chosen:
        i, j0, j1 = paths[v][:3]
        if j0:
            year0[assets[i].asset_id] = OPTION_LIST[j0]
        if j1:
            year1[assets[i].asset_id] = OPTION_LIST[j1]
    return MultiPeriodPlan(
        year0=year0,
        year1=year1,
        objective=float(res.fun),
        spend_year0=float(cost0[chosen].sum()),
        spend_total=float((cost0 + cost1)[chosen].sum()),
        n_paths=n,
        note=(
            "Two-period additive schedule: one path per asset, year-0 spend capped at the "
            "annual budget, two-year spend capped at twice it (unspent money carries "
            "forward). Deterioration is the rounded expectation of the fitted transition "
            "matrix; loss uses the optimizer's mean rainfall sample. Emergency repairs and "
            "network coupling are not in the model and are supplied by the simulator when "
            "the schedule is replayed."
        ),
    )
