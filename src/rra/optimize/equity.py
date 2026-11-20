"""Equity-weighted additive allocation and the price of redistribution.

The paper reports a Gini of the plan's benefit but never asks what reducing it would cost.
The obvious instrument — a hard floor on the benefit every habitation receives — is
degenerate here: coverage is close to disjoint, so with a binding budget any single
unfunded habitation holds the feasible floor at zero. A leximin constraint on this
portfolio would report a frontier of zeros, which is a property of the coverage pattern,
not a statement about equity.

The instrument used instead is a **weight on the objective**. Each habitation's benefit is
multiplied by ``(median_population / population_h) ** exponent``:

* ``exponent = 0`` reproduces the reported population-weighted plan exactly;
* ``exponent = 1`` counts every habitation equally, so a hamlet of 40 people weighs as much
  as a town of 40,000.

Sweeping the exponent gives a linear, non-degenerate frontier, and the difference in the
*unweighted* additive loss between two exponents is the efficiency the redistribution
costs. Per-habitation benefit is still a first-order attribution of each asset's measured
solo loss, so the frontier is a statement about how the plan distributes measured
consequence, not a re-solve of the joint network.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from .milp import AdditiveInstance


@dataclass
class EquityFrontier:
    """The exponent frontier plus the reference row it is measured against."""

    rows: list
    n_habitations_eligible: int
    n_habitations_total: int
    base_objective: float
    note: str

    def as_dict(self) -> dict:
        return {
            "rows": self.rows,
            "n_habitations_eligible": self.n_habitations_eligible,
            "n_habitations_total": self.n_habitations_total,
            "base_objective": self.base_objective,
            "note": self.note,
        }


def benefit_by_habitation(inst: AdditiveInstance, solo_share: dict) -> tuple[np.ndarray, list]:
    """``benefit[v, h]``: additive benefit of option ``v`` attributed to habitation ``h``.

    ``solo_share[a]`` is ``{habitation: loss contribution}`` from the accessibility model,
    summing to the asset's solo loss. A row therefore sums to the option's total additive
    benefit, which is what makes the weighted objective comparable with the base plan.
    """
    habitations = sorted({h for share in solo_share.values() for h in share})
    index = {h: i for i, h in enumerate(habitations)}
    out = np.zeros((inst.n_vars, len(habitations)))
    mean_loss = inst.loss.mean(axis=1)
    for group in inst.asset_groups:
        base = float(mean_loss[group[0]])  # NONE option
        asset_id = inst.option_names[group[0]].split(":", 1)[0]
        share = solo_share.get(asset_id) or {}
        total = float(sum(share.values()))
        if total <= 0:
            continue
        for v in group:
            gain = base - float(mean_loss[v])
            if gain == 0.0:
                continue
            for h, value in share.items():
                out[v, index[h]] += gain * (value / total)
    return out, habitations


def _solve(inst: AdditiveInstance, budget: float, crew: float, cost: np.ndarray):
    """One MILP over the asset-option decisions with the supplied objective vector."""
    n = inst.n_vars
    rows, lb, ub = [], [], []
    row = np.zeros(n); row[:] = inst.cost
    rows.append(row); lb.append(-np.inf); ub.append(budget)
    row = np.zeros(n); row[:] = inst.labour
    rows.append(row); lb.append(-np.inf); ub.append(crew)
    for group in inst.asset_groups:
        row = np.zeros(n); row[group] = 1.0
        rows.append(row); lb.append(1.0); ub.append(1.0)
    res = milp(
        c=np.asarray(cost, dtype=float),
        constraints=LinearConstraint(np.vstack(rows), np.array(lb), np.array(ub)),
        integrality=np.ones(n, dtype=int),
        bounds=Bounds(np.zeros(n), np.ones(n)),
    )
    if res.x is None:  # pragma: no cover - the NONE option is always feasible
        return None
    return res


def _gini(values) -> float:
    v = np.sort(np.asarray(values, dtype=float))
    n = v.size
    if n == 0 or v.sum() <= 0:
        return 0.0
    idx = np.arange(1, n + 1)
    return float((2 * (idx * v).sum()) / (n * v.sum()) - (n + 1) / n)


def _plan_stats(inst, x, benefit, populations) -> dict:
    x = np.asarray(x[: inst.n_vars], dtype=float)
    per_hab = benefit.T @ x
    funded = int(sum(1 for group in inst.asset_groups if x[group].argmax() != 0))
    reached = [
        (v, p) for v, p in zip(per_hab, populations) if v > 0 and p > 0
    ]
    per_capita = sorted((v / p for v, p in reached), reverse=True)
    return {
        "funded": funded,
        "spend_crore": float(inst.cost @ x),
        "crew_days": float(inst.labour @ x),
        "objective": float(inst.loss.mean(axis=1) @ x),
        "total_benefit": float(per_hab.sum()),
        "min_habitation_benefit": float(per_hab.min()) if per_hab.size else 0.0,
        "p10_habitation_benefit": float(np.quantile(per_hab, 0.10)) if per_hab.size else 0.0,
        "n_habitations_with_benefit": len(reached),
        "gini_of_benefit_per_person": _gini(per_capita),
    }


def equity_frontier(
    inst: AdditiveInstance,
    solo_share: dict,
    populations: dict,
    budget: float,
    crew: float,
    exponents=(0.0, 0.5, 1.0, 1.5),
) -> EquityFrontier:
    """Sweep the habitation-size weight and report the efficiency it costs.

    The row at exponent 0 is the reported plan and is the reference for every other row:
    ``benefit_lost_vs_efficiency`` is the increase in the *unweighted* additive loss, i.e.
    person-days the district gives up in total in order to spread the plan more equally.
    """
    benefit, habitations = benefit_by_habitation(inst, solo_share)
    eligible = benefit.max(axis=0) > 0
    benefit = benefit[:, eligible]
    habitations = [h for h, keep in zip(habitations, eligible) if keep]
    pops = [float(populations.get(h, 0.0)) for h in habitations]
    positive = [p for p in pops if p > 0]
    reference = float(np.median(positive)) if positive else 1.0

    rows = []
    base = None
    for exponent in exponents:
        pop_array = np.maximum(np.asarray(pops, dtype=float), 1e-9)
        weights = (reference / pop_array) ** float(exponent) if exponent else np.ones(len(pops))
        cost = -(benefit @ weights)
        res = _solve(inst, budget, crew, cost)
        if res is None:  # pragma: no cover
            rows.append({"exponent": float(exponent), "infeasible": True})
            continue
        stats = _plan_stats(inst, res.x, benefit, pops)
        stats["exponent"] = float(exponent)
        if base is None:
            base = stats
            stats["benefit_lost_vs_efficiency"] = 0.0
            stats["gini_change_vs_efficiency"] = 0.0
        else:
            stats["benefit_lost_vs_efficiency"] = float(
                stats["objective"] - base["objective"]
            )
            stats["gini_change_vs_efficiency"] = float(
                stats["gini_of_benefit_per_person"] - base["gini_of_benefit_per_person"]
            )
        rows.append(stats)

    return EquityFrontier(
        rows=rows,
        n_habitations_eligible=int(benefit.shape[1]),
        n_habitations_total=int(benefit.shape[1] + (~eligible).sum()),
        base_objective=float(base["objective"]) if base else float("nan"),
        note=(
            "Objective weight is (median population / habitation population) ** exponent. "
            "Exponent 0 reproduces the reported population-weighted plan; higher exponents "
            "count small habitations more heavily. Benefit per habitation is a first-order "
            "attribution of each asset's measured solo loss, not a joint re-solve. The Gini "
            "is computed over habitations that receive any benefit, matching the reported "
            "equity block."
        ),
    )
