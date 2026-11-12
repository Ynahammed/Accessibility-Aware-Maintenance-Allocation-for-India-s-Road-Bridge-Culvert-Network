"""The recommended maintenance plan for a district, budget and horizon.

This is the product-layer answer to "what should we repair this year with ₹X crore?".
It runs the paired simulator (do-nothing, condition-first, additive MILP, network-aware)
on shared scenarios and returns the network-aware plan as auditable rows: condition,
option, cost, labour, condition after the repair, the fragility multiplier it buys, and
the accessibility loss of that structure failing alone. Budget and crew are hard
constraints — a plan that breaches either is rejected before it is returned.
"""

from __future__ import annotations

import numpy as np

from rra.cost.interventions import Intervention, apply_effect
from rra.deterioration.markov import STATES
from rra.evaluate import stats
from rra.simulator import policies, step
from rra.simulator.optimized_policies import AdditiveMilpPolicy, NetworkAwarePolicy

from .districts import build_world_models, get_spec, summarize
from .register import live_register


class _Recorder:
    """Capture a policy's first-year plan."""

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.plan: dict | None = None

    def propose(self, assets, ctx):
        chosen = self.inner.propose(assets, ctx)
        if self.plan is None:
            self.plan = dict(chosen)
        return chosen


def build_plan(
    district_id: str,
    budget_crore: float | None = None,
    crew_days: float | None = None,
    seed: int = 0,
    scenarios: int = 8,
    years: int = 1,
) -> dict:
    """Return the year-1 network-aware plan plus paired loss outcomes."""
    spec = get_spec(district_id)
    if spec.status != "ready":
        raise ValueError(f"district {district_id!r} has no allocation layer ({spec.status})")

    live = live_register()
    district, models, world = build_world_models(district_id, seed, live=live)
    if budget_crore is not None:
        world.budget_crore = max(0.0, float(budget_crore))
    if crew_days is not None:
        world.crew_days = max(0.0, float(crew_days))

    asset_ids = list(world.assets)
    n_assets = len(asset_ids)
    rng = np.random.default_rng(seed + 17)
    stress = 0.9 if spec.preset == "redundant" else 0.0
    sigma = 0.15 if spec.preset == "redundant" else 0.4
    rain = np.exp(rng.normal(stress, sigma, size=(scenarios, years, n_assets)))
    scen = step.make_scenarios(asset_ids, years, scenarios, rng, rain=rain)
    opt_rain = np.exp(
        np.random.default_rng(seed + 999).normal(
            stress, sigma, size=(max(scenarios, 8), n_assets)
        )
    )

    recorder = _Recorder(NetworkAwarePolicy(models, opt_rain, seed=seed))
    policy_list = [
        _Recorder(policies.DoNothingPolicy()),
        _Recorder(policies.WorstFirstPolicy()),
        _Recorder(AdditiveMilpPolicy(models, opt_rain, seed=seed)),
        recorder,
    ]
    outcomes = {p.name: step.run(p, world, scen, models) for p in policy_list}

    chosen = recorder.plan or {}
    rows = []
    spent = 0.0
    used = 0.0
    for asset in world.assets.values():
        opt = chosen.get(asset.asset_id, Intervention.NONE)
        effect = models.effect(opt)
        cost = float(models.sor.cost(asset.structure_type, opt))
        labour = float(models.sor.labour(asset.structure_type, opt))
        after = apply_effect(asset.condition, effect)
        factor = effect.fragility_factor
        spent += cost
        used += labour
        if opt is Intervention.NONE:
            reason = "not funded: outside the budget-ranked set"
        else:
            reason = (
                f"{opt.value} repair resets condition {STATES[int(asset.condition)]} -> "
                f"{STATES[int(after)]} and multiplies failure odds by {factor:.2f}"
            )
        rows.append(
            {
                "id": asset.asset_id,
                "type": asset.structure_type,
                "condition": int(asset.condition),
                "state": STATES[int(asset.condition)],
                "recommended": opt.value,
                "cost_crore": cost,
                "labour_days": labour,
                "condition_after": int(after),
                "state_after": STATES[int(after)],
                "fragility_factor": factor,
                "solo_loss": float(models.acc.loss(failed_nodes=[asset.node])),
                "reason": reason,
                "funded": opt is not Intervention.NONE,
            }
        )
    rows.sort(key=lambda r: (not r["funded"], -r["cost_crore"], r["id"]))

    if spent > world.budget_crore + 1e-6 or used > world.crew_days + 1e-6:
        raise RuntimeError("optimizer returned a plan outside the budget/crew constraint")

    ci = stats.paired_bootstrap_ci(
        outcomes["worst_first"].person_days,
        outcomes["network_aware"].person_days,
        n=2000,
        rng=seed,
    )
    means = {name: float(out.person_days.mean()) for name, out in outcomes.items()}
    return {
        "ok": True,
        "district": summarize(district_id, seed),
        "seed": seed,
        "scenarios": scenarios,
        "years": years,
        "budget_crore": float(world.budget_crore),
        "crew_days": float(world.crew_days),
        "policy": "network_aware",
        "recommendations": rows,
        "planned_spend_crore": spent,
        "crew_days_used": used,
        "n_funded": int(sum(1 for r in rows if r["funded"])),
        "loss": {
            "mean_person_days": means,
            "paired_worst_first_minus_network_aware": {
                "mean": float(ci.mean),
                "ci_lo": float(ci.lo),
                "ci_hi": float(ci.hi),
                "n_scenarios": int(scen.n),
            },
        },
        "provenance": {
            "district": spec.provenance,
            "costs": models.sor.source,
            "register": live.describe(),
            "note": (
                "Simulator-only recommendation on a seeded synthetic district; every "
                "assumption is in the register and varied in E8."
            ),
        },
    }
