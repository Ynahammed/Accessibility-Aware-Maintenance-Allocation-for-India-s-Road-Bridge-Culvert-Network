import numpy as np
import pytest

from rra.optimize import milp
from rra.optimize.cvar import cvar, value_at_risk
from rra.optimize.local_search import (
    local_search,
    multi_start_local_search,
    selection_to_x,
)


def test_cvar_and_var():
    losses = [1, 2, 3, 4, 5]
    assert cvar(losses, alpha=0.2) == pytest.approx(5.0)  # worst single
    assert cvar(losses, alpha=0.4) == pytest.approx(4.5)  # worst two
    assert value_at_risk(losses, alpha=0.2) == pytest.approx(4.0, abs=0.6)
    with pytest.raises(ValueError):
        cvar(losses, alpha=0.0)


def make_instance(n_assets=6, S=20, seed=0, repair_factor=0.4):
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.0, 100.0, size=(n_assets, S))
    cost = np.zeros(2 * n_assets)
    labour = np.zeros(2 * n_assets)
    loss = np.zeros((2 * n_assets, S))
    groups, names = [], []
    for a in range(n_assets):
        loss[2 * a] = base[a]                      # NONE
        loss[2 * a + 1] = base[a] * repair_factor  # REPAIR
        cost[2 * a + 1] = rng.uniform(1.0, 10.0)
        labour[2 * a + 1] = rng.uniform(2.0, 8.0)
        groups.append([2 * a, 2 * a + 1])
        names += [f"a{a}:none", f"a{a}:repair"]
    return milp.AdditiveInstance(cost, labour, loss, groups, names)


def test_zero_budget_reproduces_do_nothing():
    inst = make_instance()
    x, val, _ = milp.solve_additive(inst, budget=0.0, crew=1e9)
    assert all(x[g[0]] == 1 for g in inst.asset_groups)  # every asset -> NONE
    # objective = sum over assets of the per-scenario mean loss
    do_nothing = inst.loss[[g[0] for g in inst.asset_groups]].mean(axis=1).sum()
    assert val == pytest.approx(do_nothing)


def test_more_budget_never_raises_optimal_loss():
    inst = make_instance()
    prev = None
    for budget in [0.0, 10.0, 25.0, 50.0, 1000.0]:
        _, val, _ = milp.solve_additive(inst, budget=budget, crew=1e9)
        if prev is not None:
            assert val <= prev + 1e-6
        prev = val


def test_solution_respects_budget_and_crew():
    inst = make_instance()
    budget, crew = 20.0, 15.0
    x, _, _ = milp.solve_additive(inst, budget=budget, crew=crew)
    assert milp.is_feasible(inst, x, budget, crew)
    assert inst.cost @ x <= budget + 1e-6
    assert inst.labour @ x <= crew + 1e-6


def test_solver_is_reproducible():
    inst = make_instance()
    x1, v1, _ = milp.solve_additive(inst, budget=20.0, crew=15.0)
    x2, v2, _ = milp.solve_additive(inst, budget=20.0, crew=15.0)
    assert np.array_equal(x1, x2)
    assert v1 == pytest.approx(v2)


def test_cvar_term_penalises_tail():
    inst = make_instance(seed=1)
    _, _, _ = milp.solve_additive(inst, budget=20.0, crew=1e9, lam=0.0)
    x_tail, val_tail, _ = milp.solve_additive(inst, budget=20.0, crew=1e9, lam=2.0, alpha=0.1)
    lw = milp.scenario_losses(inst, x_tail)
    # the tail-aware solution should not have a worse CVaR than the mean-only one
    x_mean, _, _ = milp.solve_additive(inst, budget=20.0, crew=1e9, lam=0.0)
    assert cvar(lw, 0.1) <= cvar(milp.scenario_losses(inst, x_mean), 0.1) + 1e-6


def test_local_search_matches_additive_optimum():
    inst = make_instance(seed=2)

    def objective(x):
        return float(milp.scenario_losses(inst, x).mean())

    # start from all NONE; with a generous budget the optimum is all-REPAIR
    start = [g[0] for g in inst.asset_groups]
    sel, val = local_search(inst.asset_groups, start, objective, n_vars=inst.n_vars)
    _, milp_val, _ = milp.solve_additive(inst, budget=1e9, crew=1e9)
    assert val == pytest.approx(milp_val, abs=1e-6)
    assert all(sel[a] == inst.asset_groups[a][1] for a in range(len(inst.asset_groups)))


def test_selection_to_x_is_one_hot():
    x = selection_to_x([0, 3], n_vars=4)
    assert x.tolist() == [1.0, 0.0, 0.0, 1.0]


def _budget_trade_problem():
    """One asset already repaired; a cheaper asset is a much better repair.

    Budget 10. Asset 0's repair costs 10 and saves 1; assets 1 and 2 cost 5 and save 5
    each. Starting from [repair0, none, none] every single move is either infeasible
    (funding another repair needs 5 more) or worse (dropping asset 0's repair loses 1).
    Only a two-asset trade can improve: drop asset 0, repair asset 1.
    """
    groups = [[0, 1], [2, 3], [4, 5]]
    cost = np.array([0.0, 10.0, 0.0, 5.0, 0.0, 5.0])
    loss = np.array([5.0, 4.0, 5.0, 0.0, 5.0, 0.0])
    budget = 10.0

    def objective(x):
        return float(loss @ np.asarray(x, dtype=float))

    def feasible(sel):
        return float(cost[sel].sum()) <= budget + 1e-9

    return groups, [1, 2, 4], objective, feasible


def test_pair_moves_free_budget_for_a_better_repair():
    groups, start, objective, feasible = _budget_trade_problem()
    single, single_val = local_search(
        groups, start, objective, n_vars=6, pair_moves=False, feasible=feasible
    )
    pair, pair_val = local_search(
        groups, start, objective, n_vars=6, pair_moves=True, feasible=feasible
    )
    assert single == start and single_val == pytest.approx(14.0)  # stalled by the budget
    assert pair == [0, 3, 5]  # drop asset 0, repair assets 1 and 2 with the freed budget
    assert pair_val == pytest.approx(5.0)
    assert feasible(pair)


def test_local_search_never_returns_an_infeasible_selection():
    groups, start, objective, feasible = _budget_trade_problem()
    sel, _ = local_search(groups, start, objective, n_vars=6, feasible=feasible)
    assert feasible(sel)
    assert float(sum(1 for s in sel if s % 2 == 1)) == 2  # both 5-cost repairs funded


def test_multi_start_keeps_the_best_feasible_start():
    groups, start, objective, feasible = _budget_trade_problem()
    best, val = multi_start_local_search(
        groups, [[0, 2, 4], start], objective, n_vars=6, feasible=feasible
    )
    assert best == [0, 3, 5]
    assert val == pytest.approx(5.0)


def test_coverage_cut_sets_identify_parallel_corridors():
    from rra.assumptions import AssumptionRegister
    from rra.network.synthetic import make_redundant_district
    from rra.optimize.coverage import corridor_cut_sets
    from rra.pipeline import build_models, build_world

    district = make_redundant_district(n_corridors=3, redundancy=3, seed=0)
    models = build_models(district, AssumptionRegister.default())
    world = build_world(district, AssumptionRegister.default())

    cuts = corridor_cut_sets(models.acc, list(world.assets.values()))

    # one minimum cut per corridor, each containing every parallel route's structure
    assert [sorted(cut.assets) for cut in cuts] == [
        ["S0", "S1", "S2"],
        ["S3", "S4", "S5"],
        ["S6", "S7", "S8"],
    ]
    assert all(cut.weight == 400.0 for cut in cuts)  # population protected


def test_cut_sets_ignore_routes_without_structures():
    """A structure-free road means no structure cut exists; none should be invented."""
    from types import SimpleNamespace

    import networkx as nx

    from rra.optimize.coverage import CutSet, corridor_cut_sets

    graph = nx.Graph()
    graph.add_edge("H", "F")  # direct road, no structure on it
    graph.add_edge("H", "a")
    graph.add_edge("a", "S0")
    graph.add_edge("S0", "F")
    acc = SimpleNamespace(graph=graph, habitations={"H": 1.0}, facilities={"health": ["F"]})
    assets = [SimpleNamespace(asset_id="S0", node="S0")]

    assert corridor_cut_sets(acc, assets) == []

    graph.remove_edge("H", "F")  # now the single structure is the cut
    assert corridor_cut_sets(acc, assets) == [CutSet(frozenset({"S0"}), 1.0)]


def test_cut_sets_find_alternative_bottlenecks_and_weight_them_by_population():
    """A series chain has one cut per structure; both must be discovered."""
    from types import SimpleNamespace

    import networkx as nx

    from rra.optimize.coverage import corridor_cut_sets

    graph = nx.Graph()
    graph.add_edge("H", "S0")
    graph.add_edge("S0", "S1")
    graph.add_edge("S1", "F")
    acc = SimpleNamespace(graph=graph, habitations={"H": 500.0}, facilities={"health": ["F"]})
    assets = [SimpleNamespace(asset_id=f"S{i}", node=f"S{i}") for i in range(2)]

    cuts = corridor_cut_sets(acc, assets)

    assert {cut.assets for cut in cuts} == {frozenset({"S0"}), frozenset({"S1"})}
    assert all(cut.weight == 500.0 for cut in cuts)


def test_candidate_ranking_prefers_coverage_over_a_noisier_lower_loss():
    from rra.optimize.coverage import CutSet
    from rra.simulator.optimized_policies import _coverage_rank

    cuts = [CutSet(frozenset({"S0", "S1"}), 400.0)]
    index = {"S0": 0, "S1": 1}
    partial = [0, 0]  # both NONE: the cut is not covered
    full = [1, 1]

    # the partial plan scores lower on this validation draw, but that is sampling noise
    scored = [(10.0, 0.02, partial), (11.0, 0.04, full)]
    assert _coverage_rank(scored, cuts, index) is full


def test_improving_levels_drop_a_dominated_major_repair():
    from rra.app.register import apply_payload
    from rra.assumptions import AssumptionRegister
    from rra.network.synthetic import make_district
    from rra.pipeline import build_models
    from rra.simulator.optimized_policies import _improving_levels

    district = make_district(seed=0)
    default = build_models(district, AssumptionRegister.default())
    assert _improving_levels(default) == [1, 2, 3]

    live = apply_payload(
        {
            "manifest": {"application_ref": "RTI/TEST"},
            "register": {
                "repair_effect_minor": {
                    "value": 2.0, "source": "fitted", "provenance": {"n": 5}
                }
            },
        }
    )
    measured = build_models(district, live.register, sor=live.sor)
    # major costs 4x minor and now resets the same two steps: dominated
    assert _improving_levels(measured) == [1, 3]


def test_cut_sets_are_cached_per_graph_and_asset_nodes(monkeypatch):
    """Simulation proposes every scenario-year on the same topology: do the flow once."""
    from rra.assumptions import AssumptionRegister
    from rra.network.synthetic import make_redundant_district
    from rra.optimize import coverage
    from rra.optimize.coverage import corridor_cut_sets
    from rra.pipeline import build_models, build_world

    calls = {"n": 0}
    real = coverage.nx.minimum_cut

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(coverage.nx, "minimum_cut", counted)

    district = make_redundant_district(n_corridors=3, redundancy=3, seed=0)
    models = build_models(district, AssumptionRegister.default())
    world = build_world(district, AssumptionRegister.default())
    assets = list(world.assets.values())

    first = corridor_cut_sets(models.acc, assets)
    n_first = calls["n"]
    assert n_first > 0

    assert corridor_cut_sets(models.acc, assets) == first
    assert calls["n"] == n_first, "the second call must hit the cache"

    # a different structure set is a different key and must be computed
    corridor_cut_sets(models.acc, assets[:-1])
    assert calls["n"] > n_first


@pytest.mark.parametrize("redundancy, expected_cost", [(2, 0.096), (3, 0.144)])
def test_network_aware_coverage_starts_fund_every_corridor_across_seeds(redundancy, expected_cost):
    """Regression: the reply-backed plan left 5,175 person-days on a redundant district.

    Every structure's solo loss is zero there, so the additive MILP and random starts never
    complete a corridor. The coverage starts must complete every corridor for every seed,
    not only seed 0: a seed-sensitive search would leave the result one draw away from
    returning a partial corridor again. The option mix may vary with the validation draw;
    what must not vary is full coverage within budget.
    """
    from rra.app.register import apply_payload
    from rra.cost.interventions import Intervention
    from rra.network.synthetic import make_redundant_district
    from rra.pipeline import build_models, build_world
    from rra.simulator.optimized_policies import NetworkAwarePolicy
    from rra.simulator.policies import PolicyContext

    live = apply_payload(
        {
            "manifest": {"office": "EE PWD", "application_ref": "RTI/TEST"},
            "register": {
                "repair_effect_minor": {
                    "value": 2.0, "source": "fitted", "provenance": {"n": 5}
                }
            },
            "schedule_of_rates": {
                "culvert": {"value": 0.016, "source": "fitted"}
            },
            "labour_days": {"culvert": {"value": 5.0, "source": "fitted"}},
        }
    )
    district = make_redundant_district(n_corridors=3, redundancy=redundancy, seed=0)
    models = build_models(district, live.register, sor=live.sor)
    world = build_world(district, live.register)
    for asset in world.assets.values():
        asset.condition = 2  # the monsoon-stress bed the app uses

    n_assets = len(world.assets)
    ctx = PolicyContext(sor=models.sor, budget_crore=0.4, crew_days=1000.0)
    for seed in range(10):
        rain = np.exp(np.random.default_rng(seed + 999).normal(0.9, 0.15, size=(8, n_assets)))
        plan = NetworkAwarePolicy(models, rain, seed=seed).propose(
            list(world.assets.values()), ctx
        )
        assert set(plan) == {f"S{i}" for i in range(n_assets)}, f"seed {seed}: partial corridor"
        assert all(opt is not Intervention.NONE for opt in plan.values()), f"seed {seed}: none"
        # all-minor is the cheapest full coverage; a seed may upgrade a corridor when the
        # validation sample says the extra fragility reduction is worth the spend
        spend = sum(models.sor.cost("culvert", opt) for opt in plan.values())
        assert expected_cost - 1e-9 <= spend <= 0.4 + 1e-9, f"seed {seed}: spend {spend}"


def test_full_coverage_appears_exactly_when_the_budget_reaches_its_cost():
    """Coverage-first must not promise a plan the budget cannot fund."""
    from rra.app.register import apply_payload
    from rra.cost.interventions import Intervention
    from rra.network.synthetic import make_redundant_district
    from rra.pipeline import build_models, build_world
    from rra.simulator.optimized_policies import NetworkAwarePolicy
    from rra.simulator.policies import PolicyContext

    live = apply_payload(
        {
            "manifest": {"application_ref": "RTI/TEST"},
            "register": {
                "repair_effect_minor": {
                    "value": 2.0, "source": "fitted", "provenance": {"n": 5}
                }
            },
            "schedule_of_rates": {"culvert": {"value": 0.016, "source": "fitted"}},
            "labour_days": {"culvert": {"value": 5.0, "source": "fitted"}},
        }
    )
    district = make_redundant_district(n_corridors=3, redundancy=3, seed=0)
    models = build_models(district, live.register, sor=live.sor)
    world = build_world(district, live.register)
    for asset in world.assets.values():
        asset.condition = 2
    assets = list(world.assets.values())
    rain = np.exp(np.random.default_rng(999).normal(0.9, 0.15, size=(8, len(assets))))

    # cheapest full coverage is nine minor repairs at 0.016 = 0.144
    for budget, expect_full in ((0.10, False), (0.15, True), (0.24, True)):
        ctx = PolicyContext(sor=models.sor, budget_crore=budget, crew_days=1000.0)
        plan = NetworkAwarePolicy(models, rain, seed=0).propose(assets, ctx)
        funded = set(plan)
        covered = sum(
            1
            for c in range(3)
            if all(f"S{c*3+i}" in funded for i in range(3))
        )
        assert (covered == 3) is expect_full, f"budget {budget}: {covered}/3 corridors"
        spend = sum(models.sor.cost("culvert", opt) for opt in plan.values())
        assert spend <= budget + 1e-9, f"budget {budget}: spent {spend}"
        if not expect_full:
            assert covered == 2  # the most population the budget can protect


def test_multi_start_shares_one_evaluation_memo():
    """A repeated start must not repeat any objective evaluation."""
    groups, start, objective, feasible = _budget_trade_problem()

    def counted_runner(starts):
        calls = {"n": 0}

        def counted(x):
            calls["n"] += 1
            return objective(x)

        multi_start_local_search(
            groups, starts, counted, n_vars=6, pair_moves=True, feasible=feasible
        )
        return calls["n"]

    once = counted_runner([start])
    twice = counted_runner([start, start])
    assert twice == once
