"""Tests for the robustness primitives behind the paper's headline claim.

These are the pieces that could quietly change a reported number, so each is pinned on a
case whose answer can be worked out by hand:

* the TOST arithmetic and its design quantities;
* the ordering a consequence-blind rule actually produces (and the ratio flag that would
  invert it);
* one-pass ``failure_detail`` against the two-pass ``loss`` and ``disruption`` it replaces;
* the equity frontier reproducing the reported plan at weight exponent 0;
* the two-period schedule respecting the annual budget and the carryover total.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from rra.assumptions import AssumptionRegister
from rra.consequence.accessibility import AccessibilityModel
from rra.cost.interventions import Intervention
from rra.cost.sor import ScheduleOfRates
from rra.evaluate.equivalence import (
    min_detectable_difference,
    required_n,
    tost,
)
from rra.network.synthetic import make_district
from rra.optimize import milp
from rra.optimize.equity import equity_frontier
from rra.optimize.multiperiod import solve_multiperiod
from rra.pipeline import build_models, build_world
from rra.simulator import policies, step
from rra.simulator.optimized_policies import FixedPlanPolicy
from rra.simulator.policies import PolicyContext
from rra.simulator.state import Asset


# --- equivalence -------------------------------------------------------------------


def test_tost_rejects_a_clear_difference():
    diff = np.full(20, 500.0)
    diff[0] = 499.0  # avoid a zero variance, which is a separate branch
    result = tost(diff, margin=100.0)
    assert not result.equivalent
    assert result.p_tost > 0.05
    assert result.ci_lo > 100.0


def test_tost_accepts_a_tightly_estimated_null():
    rng = np.random.default_rng(0)
    diff = rng.normal(0.0, 10.0, size=400)
    result = tost(diff, margin=5.0)
    assert result.equivalent
    assert result.p_tost < 0.05


def test_tost_is_not_equivalence_without_a_sample():
    result = tost([123.0], margin=1000.0)
    assert not result.equivalent
    assert result.n == 1
    assert np.isnan(result.p_tost)


def test_design_quantities_scale_the_way_a_reader_expects():
    # four times the sample halves the minimum detectable difference
    assert min_detectable_difference(1000.0, 400) == pytest.approx(
        min_detectable_difference(1000.0, 100) / 2.0, rel=0.05
    )
    # a tighter margin needs a larger sample
    assert required_n(1000.0, 50.0) > required_n(1000.0, 100.0)
    # an unusable design reports zero rather than a made-up number
    assert required_n(0.0, 100.0) == 0


# --- consequence-blind orderings ---------------------------------------------------


def _ctx(budget: float = 0.3) -> PolicyContext:
    return PolicyContext(
        sor=ScheduleOfRates(), budget_crore=budget, crew_days=1e9, rng=np.random.default_rng(0)
    )


def _assets() -> list[Asset]:
    return [
        Asset("A", "minor_bridge", "nA", age=30, condition=1),  # minor: 0.08
        Asset("B", "culvert", "nB", age=10, condition=3),        # replace: 0.24
        Asset("C", "culvert", "nC", age=5, condition=2),         # major: 0.08
    ]


def test_age_first_funds_the_oldest_structure_first():
    chosen = policies.age_first_policy().propose(_assets(), _ctx(0.08))
    assert "A" in chosen


def test_type_first_prefers_a_bridge_over_a_culvert():
    chosen = policies.type_first_policy().propose(_assets(), _ctx(0.1))
    assert "A" in chosen
    assert not {"B", "C"} & set(chosen)


def test_cheapest_first_funds_the_cheapest_repairs():
    chosen = policies.cheapest_first_policy().propose(_assets(), _ctx(0.2))
    assert "A" in chosen and "C" in chosen
    assert "B" not in chosen  # the 0.24 replacement cannot fit next to a 0.08 repair


def test_ratio_flag_changes_the_ordering_it_is_meant_for():
    """A cost-derived score must not be divided by cost again."""
    assets = _assets()
    cost = lambda a, c: c.sor.cost(a.structure_type, policies.default_option(a))  # noqa: E731

    ranked = policies.greedy_ranked_select(
        assets, _ctx(0.3), cost, option_fn=policies.default_option, by_ratio=False
    )
    assert set(ranked) == {"B"}  # dearest first, and only it fits

    inverted = policies.greedy_ranked_select(
        assets, _ctx(0.3), cost, option_fn=policies.default_option, by_ratio=True
    )
    assert "A" in inverted  # cost/cost ties, so the caller's order decides


# --- one-pass failure detail -------------------------------------------------------


def _toy_model() -> AccessibilityModel:
    graph = nx.Graph()
    graph.add_edge("h", "a", travel_time_min=1.0)
    graph.add_edge("a", "b", travel_time_min=1.0)
    graph.add_edge("b", "f1", travel_time_min=1.0)
    graph.add_edge("h", "c", travel_time_min=1.0)
    graph.add_edge("c", "f2", travel_time_min=10.0)
    graph.add_edge("b", "f2", travel_time_min=4.0)
    return AccessibilityModel(
        graph,
        {"h": 100.0},
        {"health": ["f1", "f2"]},
        {"health": 10.0},
        {"health": 1.0},
    )


def test_failure_detail_matches_loss_and_disruption():
    model = _toy_model()
    for failed in (("a", "b"), ("b", "f1")):
        detail = model.failure_detail(failed_edges=[failed], k="health")
        total = sum(d["loss"] for d in detail.values())
        assert total == pytest.approx(model.loss(failed_edges=[failed]))
        counts = model.disruption(failed_edges=[failed], k="health")
        isolated = [h for h, d in detail.items() if d["newly_isolated"]]
        assert counts["isolated_habitations"] == len(isolated)
        assert counts["max_extra_one_way_minutes"] == pytest.approx(
            max(d.get("extra_minutes", 0.0) for d in detail.values())
        )


def test_failure_detail_separates_isolation_from_delay():
    model = _toy_model()
    isolating = model.failure_detail(failed_edges=[("a", "b")], k="health")["h"]
    delaying = model.failure_detail(failed_edges=[("b", "f1")], k="health")["h"]
    assert isolating["newly_isolated"]
    assert isolating["loss"] == pytest.approx(70.0)  # (1.0 - 3/10) * 100
    assert not delaying["newly_isolated"]
    assert delaying["loss"] == pytest.approx(30.0)   # (6/10 - 3/10) * 100


# --- equity frontier ---------------------------------------------------------------


def _equity_instance() -> milp.AdditiveInstance:
    n, S = 4, 1
    cost = np.zeros(n)
    labour = np.zeros(n)
    loss = np.zeros((n, S))
    groups, names = [], []
    for i, (gain, tag) in enumerate(((50.0, "a0"), (60.0, "a1"))):
        base = 100.0
        loss[2 * i] = base
        loss[2 * i + 1] = base - gain
        cost[2 * i + 1] = 0.02
        labour[2 * i + 1] = 1.0
        groups.append([2 * i, 2 * i + 1])
        names += [f"{tag}:none", f"{tag}:repair"]
    return milp.AdditiveInstance(cost, labour, loss, groups, names)


def test_equity_frontier_reproduces_the_efficiency_plan_at_zero():
    inst = _equity_instance()
    # a0 serves a hamlet of 10, a1 serves a town of 1000
    shares = {"a0": {"h1": 1.0}, "a1": {"h2": 1.0}}
    pops = {"h1": 10.0, "h2": 1000.0}
    frontier = equity_frontier(inst, shares, pops, budget=0.03, crew=1e9,
                               exponents=(0.0, 1.0))
    efficient, equal = frontier.rows
    assert efficient["exponent"] == 0.0
    assert efficient["objective"] == pytest.approx(140.0)  # funds a1: 100 + 40
    assert efficient["benefit_lost_vs_efficiency"] == 0.0
    # weighting the hamlet makes the plan serve it instead, at a cost in total benefit
    assert equal["objective"] == pytest.approx(150.0)  # funds a0: 50 + 100
    assert equal["benefit_lost_vs_efficiency"] == pytest.approx(10.0)


# --- scheduling -------------------------------------------------------------------


def _world():
    district = make_district(n_junctions=16, n_habitations=8, n_structures=4, seed=3)
    register = AssumptionRegister.default()
    models = build_models(district, register, seed=3)
    world = build_world(district, register, seed=3)
    return district, models, world


def test_multiperiod_schedule_respects_budget_and_carryover():
    _, models, world = _world()
    assets = list(world.assets.values())
    benefit = step.solo_benefit(world, models)
    rain = np.exp(np.random.default_rng(0).normal(0.0, 0.4, size=(4, len(assets))))
    plan = solve_multiperiod(assets, models, rain, world.budget_crore, world.crew_days,
                             solo=benefit)
    annual = world.budget_crore
    assert plan.spend_year0 <= annual + 1e-9
    assert plan.spend_total <= 2 * annual + 1e-9
    ids = {a.asset_id for a in assets}
    assert set(plan.year0) <= ids and set(plan.year1) <= ids


# --- the shared analysis runner ---------------------------------------------------


def test_portfolio_variants_runs_each_rule_it_is_given():
    """`headline.portfolio_variants` must iterate assets, not dictionary keys.

    The real-network run passes a District object whose ``assets`` map is keyed by id; a
    bare ``list(world.assets)`` yields strings and fails on the first ``a.node`` call, which
    is a bug that only shows up after half an hour of graph building.
    """
    from rra.analysis import headline

    district, _, _ = _world()
    cfg = {"seed": 3, "scenarios": 2, "years": 2, "budget_crore": 100.0,
           "crew_days": 500.0, "demand": "pmgsy", "cvar_alpha": 0.9}
    out = headline.portfolio_variants(
        cfg, [("synthetic", district, "unit test")], AssumptionRegister.default(), _Live()
    )
    (variant,) = out["variants"]
    assert variant["n_structures"] == len(district.structures)
    assert sum(variant["structure_types"].values()) == len(district.structures)
    assert {p["policy"] for p in variant["policies"]} == {
        "worst_first", "random", "benefit_cost"
    }
    # Funded counts are copied out of the plans, so a re-run must write integers where the
    # shipped artifact used to carry nulls; the port and the artifact have to agree.
    funded = {p["policy"]: p["n_funded_year1"] for p in variant["policies"]}
    assert all(isinstance(v, int) and 0 <= v <= variant["n_structures"]
               for v in funded.values()), funded
    assert funded["random"] > 0  # a 100-crore budget always funds something here
    cells = variant["destination_islanding"]
    assert {c["destination"] for c in cells} == {"health", "school"}
    assert all(c["n_single_points_of_failure"] >= 0 for c in cells)


class _Live:
    """Minimal stand-in for the live assumption register the experiment passes in."""

    sor = ScheduleOfRates()


def test_fixed_plan_replays_within_the_carryover_ledger():
    """Year 1 may spend what year 0 saved, but not more than the two-year total."""
    cheap = Asset("c1", "culvert", "nc", age=10, condition=2)        # minor: 0.02
    dear = Asset("b1", "minor_bridge", "nb", age=10, condition=2)    # minor: 0.08
    assets = [cheap, dear]
    ctx = PolicyContext(
        sor=ScheduleOfRates(), budget_crore=0.05, crew_days=150.0,
        rng=np.random.default_rng(0), year=0,
    )
    policy = FixedPlanPolicy(
        {0: {"c1": Intervention.MINOR}, 1: {"b1": Intervention.MINOR}}, name="fixed"
    )
    assert policy.propose(assets, ctx) == {"c1": Intervention.MINOR}
    ctx.year = 1  # 2 x 0.05 available, 0.02 already committed, so 0.08 fits exactly
    assert policy.propose(assets, ctx) == {"b1": Intervention.MINOR}
    ctx.year = 2  # nothing planned beyond the horizon
    assert policy.propose(assets, ctx) == {}
