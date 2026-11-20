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
    #: optional per-asset attribute used by the consequence-blind comparators
    #: (road class, for example). Kept separate from ``criticality`` so a policy that is
    #: supposed to *ignore* consequence cannot accidentally read a consequence proxy.
    attributes: dict | None = None
    #: simulated year, 0-based. Policies that replay a fixed multi-year plan need it;
    #: single-year policies ignore it, so adding it changes no existing behaviour.
    year: int = 0


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


def greedy_ranked_select(
    assets, ctx: PolicyContext, score_fn, option_fn=None, by_ratio: bool = True
) -> dict:
    """Fund assets in descending score until budget or crew runs out.

    ``score_fn(asset, ctx)`` ranks assets; ``option_fn(asset)`` chooses the intervention
    (defaults to benefit-per-₹ via :func:`_best_option`). Keeping the two separate lets
    condition-based policies ignore benefit entirely.

    ``by_ratio`` divides the score by the intervention cost, which is what a
    benefit-per-rupee rule needs. Set it false for a rule whose score *is* the ordering
    (oldest first, cheapest first, road class first): dividing a cost-derived score by
    cost would invert the intended order, which is exactly the bug a naive reuse of this
    helper would introduce into the consequence-blind comparators.
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
        key = (score / cost) if by_ratio else score
        ranked.append((key, a.asset_id, opt, cost, labour))
    # Stable sort on the score only: ties keep the caller's asset order, which is how the
    # frozen plans were produced. A secondary key would silently reorder tied assets.
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


class RankedPolicy:
    """A rule that ranks assets by one declared score and buys condition-appropriate work.

    This exists to make the consequence-blind claim testable as a *class* of rules rather
    than against a single baseline. Age-first, cheapest-first, asset-type-first and road-
    class-first all differ in what they look at, but they share the property the paper is
    about: none of them carries any information about what a failure does to access.

    The intervention is the condition-appropriate one (severe -> replace, poor -> major,
    fair -> minor), so these rules spend like practice rather than like a benefit-per-rupee
    optimiser. That keeps the comparison about the *ranking* signal, not about
    intervention choice.
    """

    def __init__(self, name, score_fn, by_ratio: bool = False):
        self.name = name
        self._score = score_fn
        self._by_ratio = bool(by_ratio)

    def propose(self, assets, ctx: PolicyContext) -> dict:
        return greedy_ranked_select(
            assets,
            ctx,
            lambda a, c: float(self._score(a, c)),
            option_fn=default_option,
            by_ratio=self._by_ratio,
        )


def age_first_policy() -> RankedPolicy:
    """Oldest structure first: the "it has been there longest" rule."""
    return RankedPolicy("age_first", lambda a, c: float(a.age) + 1.0)


def cheapest_first_policy() -> RankedPolicy:
    """Cheapest repair first: the "do the most items" rule.

    Ranked on the inverse planned cost, so the cheapest structure is funded first; the
    score is positive by construction and is not divided by cost again.
    """
    return RankedPolicy(
        "cheapest_first",
        lambda a, c: 1.0 / max(c.sor.cost(a.structure_type, default_option(a)), 1e-9),
    )


def type_first_policy() -> RankedPolicy:
    """Asset-type first (bridges before culverts), then condition within type."""
    order = {"major_bridge": 3.0, "minor_bridge": 2.0, "culvert": 1.0, "road_segment": 0.5}
    return RankedPolicy(
        "type_first",
        lambda a, c: 10.0 * order.get(a.structure_type, 1.0) + float(a.condition),
    )


def road_class_first_policy(road_class: dict) -> RankedPolicy:
    """Busiest mapped road class first, using a supplied per-asset class weight.

    ``road_class`` maps asset id to a numeric priority (motorway high, track low). It is a
    declared input, not a measurement of traffic: the district has no link counts, which is
    precisely why a traffic-weighted rule is only a proxy here.
    """
    return RankedPolicy(
        "road_class_first",
        lambda a, c: float(road_class.get(a.asset_id, 0.0)) + 0.1 * float(a.condition),
    )


#: Road classes ordered by the traffic a class-first rule implicitly assumes. OSM
#: ``highway`` values, highest assumed importance first; anything unlisted scores 0.
ROAD_CLASS_PRIORITY: dict[str, float] = {
    "motorway": 9.0,
    "trunk": 8.0,
    "primary": 7.0,
    "secondary": 6.0,
    "tertiary": 5.0,
    "unclassified": 4.0,
    "residential": 3.0,
    "service": 2.0,
    "track": 1.0,
}


BASELINE_POLICIES = (
    DoNothingPolicy(),
    RandomPolicy(),
    WorstFirstPolicy(),
    BenefitCostPolicy(),
    CriticalityWeightedPolicy(),
    SiloedPolicy(),
)
