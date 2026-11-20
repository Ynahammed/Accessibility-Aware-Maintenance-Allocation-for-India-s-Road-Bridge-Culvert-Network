"""The recommended maintenance plan for a district, budget and horizon.

This is the product-layer answer to "what should we repair this year with ₹X crore?".
It runs the paired simulator (do-nothing, condition-first, additive MILP, and the
network-aware search where registered) on shared scenarios and returns the plan as
auditable rows: condition, option, cost, labour, condition after the repair, the fragility
multiplier it buys, and the accessibility loss of that structure failing alone. Budget and
crew are hard constraints — a plan that breaches either is rejected before it is returned.

Real Alappuzha instances take minutes per plan on the 290k-node graph, so a request whose
parameters match the offline build is served from the persisted JSON with ``cached: true``;
any other budget, crew, seed, horizon or register fingerprint recomputes live.
"""

from __future__ import annotations

import math

import numpy as np

from rra.cost.interventions import Intervention, apply_effect
from rra.deterioration.markov import STATES
from rra.evaluate import stats
from rra.simulator import policies, step
from rra.simulator.optimized_policies import AdditiveMilpPolicy, NetworkAwarePolicy

from . import districts
from .districts import (
    ALLOCATION_ASSUMED,
    SELECTION_NOTE,
    allocation_artifact,
    build_world_models,
    get_spec,
    summarize,
)
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


def _persisted_plan(
    spec,
    live,
    budget_crore: float,
    crew_days: float,
    seed: int,
    scenarios: int,
    years: int,
) -> dict | None:
    """The offline plan payload when every request parameter matches it exactly.

    The register fingerprint is part of the match: a validated PWD/RTI reply changes outage
    days and prices, which the persisted rows would no longer reflect.
    """
    if spec.provenance != "real-alappuzha" or not spec.demand:
        return None
    payload = allocation_artifact(f"{spec.demand}_plan.json")
    if not payload or payload.get("ok") is not True:
        return None
    stored = (
        payload.get("budget_crore"),
        payload.get("crew_days"),
        payload.get("seed"),
        payload.get("scenarios"),
        payload.get("years"),
    )
    wanted = (budget_crore, crew_days, int(seed), int(scenarios), int(years))
    for have, want in zip(stored, wanted):
        if have is None or not math.isclose(float(have), float(want), rel_tol=1e-9, abs_tol=1e-9):
            return None
    stored_fp = (payload.get("provenance") or {}).get("register", {}).get("fingerprint")
    if stored_fp != live.describe().get("fingerprint"):
        return None
    cached = dict(payload)
    cached["cached"] = True
    cached["cached_from"] = f"data/processed/alappuzha_allocation/{spec.demand}_plan.json"
    return cached


def build_plan(
    district_id: str,
    budget_crore: float | None = None,
    crew_days: float | None = None,
    seed: int = 0,
    scenarios: int = 8,
    years: int = 1,
) -> dict:
    """Return the year-1 plan plus paired loss outcomes.

    For real Alappuzha districts, an exact parameter match against the persisted offline
    build returns that payload with ``cached: true`` instead of recomputing for minutes.
    """
    spec = get_spec(district_id)
    if spec.status != "ready":
        raise ValueError(f"district {district_id!r} has no allocation layer ({spec.status})")

    live = live_register()
    effective_budget = spec.budget_crore if budget_crore is None else max(0.0, float(budget_crore))
    effective_crew = spec.crew_days if crew_days is None else max(0.0, float(crew_days))
    cached = _persisted_plan(
        spec, live, effective_budget, effective_crew, seed, scenarios, years
    )
    if cached is not None:
        return cached

    if spec.provenance == "real-alappuzha" and not districts.layers_present():
        # Without the layers this raised FileNotFoundError from the parquet reader, which the
        # API surfaced as a 500 with an HTML/plain-text body the page could not parse.
        raise ValueError(
            f"district {district_id!r} needs the Alappuzha network layers, which this build "
            "does not include; the plan can be rebuilt locally (see REPRODUCE.md)"
        )

    district, models, world = build_world_models(district_id, seed, live=live)
    world.budget_crore = effective_budget
    world.crew_days = effective_crew

    asset_ids = list(world.assets)
    n_assets = len(asset_ids)
    rng = np.random.default_rng(seed + 17)
    real = spec.provenance == "real-alappuzha"
    stress = 0.9 if spec.preset == "redundant" else 0.0
    sigma = 0.15 if spec.preset == "redundant" else 0.4
    rain = np.exp(rng.normal(stress, sigma, size=(scenarios, years, n_assets)))
    scen = step.make_scenarios(asset_ids, years, scenarios, rng, rain=rain)
    opt_rain = np.exp(
        np.random.default_rng(seed + 999).normal(
            stress, sigma, size=(max(scenarios, 8), n_assets)
        )
    )

    # The real district graph is 290k nodes. Its measured super-additivity is rare (3 of
    # 56 corridors), so the additive MILP is the planning policy there; the network-aware
    # search's minimum-cut starts would need a max-flow per habitation on the whole graph.
    planner = (
        AdditiveMilpPolicy(models, opt_rain, seed=seed)
        if spec.planning_policy == "additive_milp"
        else NetworkAwarePolicy(models, opt_rain, seed=seed)
    )
    recorder = _Recorder(planner)
    policy_list = [
        _Recorder(policies.DoNothingPolicy()),
        _Recorder(policies.WorstFirstPolicy()),
        _Recorder(AdditiveMilpPolicy(models, opt_rain, seed=seed)),
        recorder,
    ]
    if real:
        # keep one additive policy, not two identical ones
        policy_list = [
            _Recorder(policies.DoNothingPolicy()),
            _Recorder(policies.WorstFirstPolicy()),
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
        row = {
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
            "outage_days": models.outage(asset),
            "age": int(asset.age),
            "reason": reason,
            "funded": opt is not Intervention.NONE,
        }
        if real:
            row["provenance"] = district.asset_provenance.get(asset.asset_id)
        rows.append(row)
    rows.sort(key=lambda r: (not r["funded"], -r["cost_crore"], r["id"]))

    if spent > world.budget_crore + 1e-6 or used > world.crew_days + 1e-6:
        raise RuntimeError("optimizer returned a plan outside the budget/crew constraint")

    ci = stats.paired_bootstrap_ci(
        outcomes["worst_first"].person_days,
        outcomes[recorder.name].person_days,
        n=2000,
        rng=seed,
    )
    means = {name: float(out.person_days.mean()) for name, out in outcomes.items()}
    payload = {
        "ok": True,
        "cached": False,
        "district": summarize(district_id, seed),
        "seed": seed,
        "scenarios": scenarios,
        "years": years,
        "budget_crore": float(world.budget_crore),
        "crew_days": float(world.crew_days),
        "policy": recorder.name,
        "policy_note": (
            "Additive MILP plan: on the real district graph the network-aware local search "
            "is not run (measured super-additivity is rare: 3 of 56 corridors)."
            if real
            else "Network-aware set-based local search; the additive MILP is the paired baseline."
        ),
        "recommendations": rows,
        "planned_spend_crore": spent,
        "crew_days_used": used,
        "n_funded": int(sum(1 for r in rows if r["funded"])),
        "loss": {
            "mean_person_days": means,
            "paired_worst_first_minus_plan": {
                "comparison": f"worst_first - {recorder.name}",
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
            "policy": recorder.name,
            "note": (
                "Allocation exercise on the real Alappuzha road graph with real PMGSY/"
                "Census demand and mapped OSM hospitals. The 30 structures are unverified "
                "road/water screening candidates, not an asset register; condition, age, "
                "outage days and costs are assumed and varied in E8. Not an observed "
                "condition or spending recommendation."
                if real
                else "Simulator-only recommendation on a seeded synthetic district; every "
                "assumption is in the register and varied in E8."
            ),
        },
    }
    if real:
        payload.update(
            demand_profile=spec.demand,
            verified_structures=0,
            screening=SELECTION_NOTE,
            assumed=dict(ALLOCATION_ASSUMED),
            scenario_stress=stress,
            scenario_sigma=sigma,
        )
    return payload
