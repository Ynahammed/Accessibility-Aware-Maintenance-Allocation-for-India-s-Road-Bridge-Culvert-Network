"""Allocation policies (plan section 6).

Each policy maps a budget and crew capacity to a set of interventions. They differ only
in the *score* they rank assets by, so the comparison isolates the allocation rule:

    do_nothing      - floor
    random          - sanity check
    worst_first     - lowest condition first (common agency practice)
    benefit_cost    - risk reduction per ₹, additive, no network
    criticality     - condition x socio-economic proxy (stands in for IBMS rating)
    siloed          - fixed budget split per asset class, then best within class
    network_aware   - set-based accessibility loss (proposed; from the optimizer)

Policies must not mutate the world: they return ``{asset_id: Intervention}``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rra.cost.interventions import Intervention
from rra.cost.sor import ScheduleOfRates


@dataclass
class PolicyContext:
    sor: ScheduleOfRates
    budget_crore: float
    crew_days: float
    # score[asset_id] = expected solo accessibility loss avoided by protecting it
    benefit: dict | None = None
    # socio-economic proxy for the criticality-weighted policy
    criticality: dict | None = None
    rng: np.random.Generator | None = None


OPTIONS = (Intervention.MINOR, Intervention.MAJOR, Intervention.REPLACE)

# Condition-appropriate intervention: Severe -> replace, Poor -> major, Fair -> minor.
# Used by policies that rank on condition rather than on benefit, so worst-first is
# faithful to the plan ("lowest condition first") and does not need a benefit estimate.
_CONDITION_OPTION = {
    0: Intervention.NONE,
    1: Intervention.MINOR,
    2: Intervention.MAJOR,
    3: Intervention.REPLACE,
}


def default_option(asset) -> Intervention:
    return _CONDITION_OPTION[int(asset.condition)]


def _best_option(asset, ctx: PolicyContext):
    """Pick the intervention with the best benefit per ₹ for one asset."""
    best, best_ratio = Intervention.NONE, 0.0
    benefit = (ctx.benefit or {}).get(asset.asset_id, 0.0)
    for opt in OPTIONS:
        cost = ctx.sor.cost(asset.structure_type, opt)
        if cost <= 0:
            continue
        ratio = benefit / cost
        if ratio > best_ratio:
            best, best_ratio = opt, ratio
    return best, best_ratio


def greedy_ranked_select(assets, ctx: PolicyContext, score_fn, option_fn=None) -> dict:
    """Fund assets in descending score-per-₹ until budget or crew runs out.

    ``score_fn(asset, ctx)`` ranks assets; ``option_fn(asset)`` chooses the intervention
    (defaults to benefit-per-₹ via :func:`_best_option`). Keeping the two separate lets
    condition-based policies ignore benefit entirely.
    """
    if option_fn is None:
        option_fn = lambda a: _best_option(a, ctx)[0]  # noqa: E731
    ranked = []
    for a in assets:
        opt = option_fn(a)
        if opt is Intervention.NONE:
            continue
        cost = ctx.sor.cost(a.structure_type, opt)
        labour = ctx.sor.labour(a.structure_type, opt)
        score = score_fn(a, ctx)
        if cost <= 0 or score <= 0:
            continue
        ranked.append((score / cost, a.asset_id, opt, cost, labour))
    ranked.sort(key=lambda t: t[0], reverse=True)

    chosen: dict = {}
    spent = 0.0
    used = 0.0
    for _, asset_id, opt, cost, labour in ranked:
        if spent + cost <= ctx.budget_crore + 1e-9 and used + labour <= ctx.crew_days + 1e-9:
            chosen[asset_id] = opt
            spent += cost
            used += labour
    return chosen


class DoNothingPolicy:
    name = "do_nothing"

    def propose(self, assets, ctx: PolicyContext) -> dict:
        return {}


class RandomPolicy:
    name = "random"

    def propose(self, assets, ctx: PolicyContext) -> dict:
        rng = ctx.rng or np.random.default_rng(0)
        order = list(assets)
        rng.shuffle(order)
        chosen, spent, used = {}, 0.0, 0.0
        for a in order:
            opt, _ = _best_option(a, ctx)
            if opt is Intervention.NONE:
                continue
            cost = ctx.sor.cost(a.structure_type, opt)
            labour = ctx.sor.labour(a.structure_type, opt)
            if spent + cost <= ctx.budget_crore + 1e-9 and used + labour <= ctx.crew_days + 1e-9:
                chosen[a.asset_id] = opt
                spent += cost
                used += labour
        return chosen


class WorstFirstPolicy:
    name = "worst_first"

    def propose(self, assets, ctx: PolicyContext) -> dict:
        return greedy_ranked_select(
            assets, ctx, lambda a, c: float(a.condition), option_fn=default_option
        )


class BenefitCostPolicy:
    name = "benefit_cost"

    def propose(self, assets, ctx: PolicyContext) -> dict:
        return greedy_ranked_select(
            assets, ctx, lambda a, c: (c.benefit or {}).get(a.asset_id, 0.0)
        )


class CriticalityWeightedPolicy:
    name = "criticality_weighted"

    def propose(self, assets, ctx: PolicyContext) -> dict:
        return greedy_ranked_select(
            assets,
            ctx,
            lambda a, c: float(a.condition) * (c.criticality or {}).get(a.asset_id, 1.0),
            option_fn=default_option,
        )


class SiloedPolicy:
    """Fixed budget split per structure type, then best-within-class."""

    name = "siloed"

    def propose(self, assets, ctx: PolicyContext) -> dict:
        types = sorted({a.structure_type for a in assets})
        per_type_budget = ctx.budget_crore / max(len(types), 1)
        per_type_crew = ctx.crew_days / max(len(types), 1)
        chosen: dict = {}
        for t in types:
            subset = [a for a in assets if a.structure_type == t]
            sub_ctx = PolicyContext(
                ctx.sor, per_type_budget, per_type_crew, ctx.benefit, ctx.criticality, ctx.rng
            )
            chosen.update(
                greedy_ranked_select(
                    subset, sub_ctx, lambda a, c: (c.benefit or {}).get(a.asset_id, 0.0),
                    option_fn=default_option,
                )
            )
        return chosen


BASELINE_POLICIES = (
    DoNothingPolicy(),
    RandomPolicy(),
    WorstFirstPolicy(),
    BenefitCostPolicy(),
    CriticalityWeightedPolicy(),
    SiloedPolicy(),
)
