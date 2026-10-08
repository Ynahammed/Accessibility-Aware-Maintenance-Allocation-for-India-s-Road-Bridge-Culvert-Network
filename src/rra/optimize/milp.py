"""Additive MILP baseline (plan section 5.7).

With common random numbers, choosing option ``j`` for asset ``a`` has a *fixed* expected
loss in each scenario ``omega`` — so the additive model is a linear program with binary
decisions ``x``:

    min_x   (1/|Omega|) sum_w l_w(x)
            + lambda * ( eta + 1/((1-alpha)|Omega|) sum_w z_w )
    s.t.    z_w >= l_w(x) - eta,  z_w >= 0
            sum_{a,j} c_aj x_aj <= B          (budget)
            sum_{a,j} u_aj x_aj <= W          (crew-days)
            sum_j x_aj = 1   for each asset    (exactly one option; NONE is an option)

Keeping a zero-cost ``NONE`` option and forcing *exactly one* option per asset is what
makes "zero budget reproduces do-nothing" hold, and makes more budget never raise the
optimal loss. Solved to optimality with SciPy's HiGHS MILP backend.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


@dataclass
class AdditiveInstance:
    """Ragged option structure flattened into arrays.

    ``asset_groups`` is a list of index lists; ``asset_groups[a]`` are the flat variable
    indices for asset ``a`` (its options, the first being NONE).
    """

    cost: np.ndarray  # (n_vars,)
    labour: np.ndarray  # (n_vars,)
    loss: np.ndarray  # (n_vars, n_scenarios)
    asset_groups: list
    option_names: list  # (n_vars,) labels

    @property
    def n_vars(self) -> int:
        return self.cost.size

    @property
    def n_scenarios(self) -> int:
        return self.loss.shape[1]


def is_feasible(inst: AdditiveInstance, x, budget: float, crew: float) -> bool:
    x = np.asarray(x, dtype=float)
    if (inst.cost @ x) > budget + 1e-6 or (inst.labour @ x) > crew + 1e-6:
        return False
    return all(abs(x[g].sum() - 1.0) < 1e-6 for g in inst.asset_groups)


def scenario_losses(inst: AdditiveInstance, x) -> np.ndarray:
    """Per-scenario loss vector ``l_w(x)`` for a decision vector."""
    return np.asarray(inst.loss, dtype=float).T @ np.asarray(x, dtype=float)


def objective(inst: AdditiveInstance, x, lam: float = 0.0, alpha: float = 0.05) -> float:
    """The plan's objective: mean loss + ``lambda`` * CVaR."""
    from .cvar import cvar

    lw = scenario_losses(inst, x)
    return float(lw.mean() + lam * cvar(lw, alpha))


def solve_additive(
    inst: AdditiveInstance,
    budget: float,
    crew: float,
    lam: float = 0.0,
    alpha: float = 0.05,
    time_limit: float | None = None,
):
    """Solve the additive MILP. Returns ``(x, objective_value, result)``."""
    n = inst.n_vars
    S = inst.n_scenarios
    n_tot = n + 1 + S  # x, eta, z_1..S

    c = np.zeros(n_tot)
    c[:n] = inst.loss.mean(axis=1)  # mean loss term
    if lam > 0:
        c[n] = lam  # eta
        c[n + 1:] = lam / ((1.0 - alpha) * S)  # z

    rows = []
    lb = []
    ub = []

    # budget
    row = np.zeros(n_tot); row[:n] = inst.cost
    rows.append(row); lb.append(-np.inf); ub.append(budget)
    # crew
    row = np.zeros(n_tot); row[:n] = inst.labour
    rows.append(row); lb.append(-np.inf); ub.append(crew)
    # exactly one option per asset
    for g in inst.asset_groups:
        row = np.zeros(n_tot); row[g] = 1.0
        rows.append(row); lb.append(1.0); ub.append(1.0)
    # z_w >= l_w(x) - eta  ->  l_w(x) - eta - z_w <= 0
    for w in range(S):
        row = np.zeros(n_tot)
        row[:n] = inst.loss[:, w]
        row[n] = -1.0
        row[n + 1 + w] = -1.0
        rows.append(row); lb.append(-np.inf); ub.append(0.0)

    A = np.vstack(rows)
    constraints = LinearConstraint(A, np.array(lb), np.array(ub))

    integrality = np.zeros(n_tot, dtype=int)
    integrality[:n] = 1

    lower = np.concatenate([np.zeros(n), [-np.inf], np.zeros(S)])
    upper = np.concatenate([np.ones(n), [np.inf], np.full(S, np.inf)])
    bounds = Bounds(lower, upper)

    options = {}
    if time_limit is not None:
        options["time_limit"] = time_limit

    res = milp(c=c, constraints=constraints, integrality=integrality, bounds=bounds,
               options=options)
    if res.x is None:
        raise RuntimeError(f"MILP failed: {res.message}")
    x = np.round(res.x[:n]).astype(int)
    return x, float(res.fun), res
