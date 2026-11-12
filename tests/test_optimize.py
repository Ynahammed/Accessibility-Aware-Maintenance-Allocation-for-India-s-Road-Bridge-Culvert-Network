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
