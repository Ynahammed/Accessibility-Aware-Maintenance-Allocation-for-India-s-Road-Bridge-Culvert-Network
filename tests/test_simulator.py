import numpy as np

from rra.consequence.accessibility import AccessibilityModel
from rra.cost.sor import ScheduleOfRates
from rra.deterioration import markov
from rra.fragility.fragility import FragilityParams
from rra.network import build
from rra.simulator import policies, step
from rra.simulator.state import Asset, World


def bridge_world():
    g = build.new_graph()
    build.add_point(g, "h", 0, 0, "habitation")
    build.add_point(g, "m", 500, 0, "structure")
    build.add_point(g, "f", 1000, 0, "facility")
    build.add_road(g, "h", "m", 600, "rural")
    build.add_road(g, "m", "f", 600, "rural")
    acc = AccessibilityModel(g, {"h": 100.0}, {"health": ["f"]}, {"health": 60.0}, {"health": 1.0})
    return acc


def models_and_world():
    acc = bridge_world()
    counts = np.zeros((4, 4))
    for i in range(3):
        counts[i, i + 1] = 6.0
    counts[3, 3] = 10.0
    P = markov.fit_transition_matrix(counts)
    models = step.SimModels(
        acc=acc,
        transition=P,
        fragility=FragilityParams(beta0=-2.0, beta1=1.0, beta2=1.5),
        sor=ScheduleOfRates(),
        outage_days={"A1": 30.0},
        premium=1.8,
    )
    world = World(
        assets={"A1": Asset("A1", "minor_bridge", "m", age=5, condition=1)},
        budget_crore=50.0,
        crew_days=200.0,
    )
    return models, world


def test_make_scenarios_shapes_and_reproducibility():
    a = step.make_scenarios(["x", "y"], years=3, n=5, rng=0)
    b = step.make_scenarios(["x", "y"], years=3, n=5, rng=0)
    assert a.rain[0][0].shape == (2,)
    assert len(a.det_u) == 5 and len(a.det_u[0]) == 3
    assert np.array_equal(a.det_u[0][0], b.det_u[0][0])
    assert np.array_equal(a.fail_u[2][1], b.fail_u[2][1])


def test_run_is_paired_and_deterministic():
    models, world = models_and_world()
    scen = step.make_scenarios(["A1"], years=4, n=12, rng=1)
    o1 = step.run(policies.DoNothingPolicy(), world, scen, models)
    o2 = step.run(policies.DoNothingPolicy(), world, scen, models)
    assert np.array_equal(o1.person_days, o2.person_days)  # paired + seeded
    assert o1.person_days.shape == (12,)


def test_do_nothing_spends_nothing_planned_and_loss_is_nonnegative():
    models, world = models_and_world()
    scen = step.make_scenarios(["A1"], years=4, n=12, rng=2)
    out = step.run(policies.DoNothingPolicy(), world, scen, models)
    # do-nothing makes no planned interventions; failures still cost an emergency repair
    assert np.all(out.planned == 0.0)
    assert np.all(out.person_days >= 0.0)
    assert np.allclose(out.spend, out.planned + out.emergency)


def test_no_failures_means_no_spend():
    models, world = models_and_world()
    models.fragility = FragilityParams(beta0=-60.0, beta1=1.0, beta2=1.5)  # p ~ 0
    scen = step.make_scenarios(["A1"], years=4, n=10, rng=9)
    out = step.run(policies.DoNothingPolicy(), world, scen, models)
    assert np.all(out.spend == 0.0)


def test_baseline_policies_run_end_to_end():
    models, world = models_and_world()
    scen = step.make_scenarios(["A1"], years=4, n=15, rng=3)
    results = step.run_all(policies.BASELINE_POLICIES, world, scen, models)
    assert set(results) >= {"do_nothing", "worst_first", "benefit_cost", "siloed"}
    for name, out in results.items():
        assert out.person_days.shape == (15,)
        assert np.all(out.person_days >= 0.0)

    # the spending policies actually spend something
    assert results["worst_first"].spend.mean() > 0.0
