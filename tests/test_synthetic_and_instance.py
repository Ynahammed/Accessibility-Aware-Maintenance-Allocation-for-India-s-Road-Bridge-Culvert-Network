import numpy as np

from rra.assumptions import AssumptionRegister
from rra.network import build
from rra.network.synthetic import make_district
from rra.optimize.instance import (
    N_OPTIONS,
    OPTION_LIST,
    build_additive_instance,
    failure_indicators,
    network_aware_objective,
)
from rra.pipeline import build_models, build_world
from rra.simulator.optimized_policies import AdditiveMilpPolicy, NetworkAwarePolicy
from rra.simulator.policies import PolicyContext


def setup():
    register = AssumptionRegister.default()
    district = make_district(n_junctions=20, n_habitations=12, n_structures=8, seed=3)
    models = build_models(district, register, seed=3)
    world = build_world(district, register, seed=3)
    return district, models, world


def test_synthetic_district_passes_network_qa():
    district, _, _ = setup()
    rep = build.qa_report(
        district.graph,
        facility_nodes={"health": district.facilities["health"]},
        habitation_nodes=list(district.habitations),
    )
    assert rep.passes
    assert rep.share_habitations_with_health == 1.0
    assert len(district.structures) == 8


def test_redundant_district_is_non_additive():
    from rra.consequence.accessibility import AccessibilityModel
    from rra.network.synthetic import make_redundant_district

    d = make_redundant_district(n_corridors=1, redundancy=2, seed=0)
    acc = AccessibilityModel(
        d.graph, d.habitations, d.facilities, {"health": 60.0}, {"health": 1.0}
    )
    nodes = [n for _, n, _ in d.structures]
    solo = [acc.loss(failed_nodes=[n]) for n in nodes]
    joint = acc.loss(failed_nodes=nodes)
    assert all(s == 0.0 for s in solo)  # each structure is harmless alone
    assert joint > 0.0  # together they cut the habitation off


def test_acceleration_increases_worsening():
    from rra.pipeline import default_transition

    slow = default_transition(acceleration=1.0)
    fast = default_transition(acceleration=3.0)
    # staying Good is less likely and worsening from Good is more likely when accelerated
    assert fast[0, 0] < slow[0, 0]
    assert fast[0, 1] > slow[0, 1]


def test_additive_instance_shapes_and_none_is_free():
    district, models, world = setup()
    assets = list(world.assets.values())
    na = len(assets)
    rain = np.exp(np.random.default_rng(0).normal(0, 0.4, size=(6, na)))
    inst = build_additive_instance(assets, models, rain)
    assert inst.n_vars == na * N_OPTIONS
    assert inst.loss.shape == (na * N_OPTIONS, 6)
    assert np.all(inst.loss >= 0)
    for i in range(na):
        assert inst.cost[i * N_OPTIONS] == 0.0  # NONE is free
        assert OPTION_LIST[0].value == "none"


def test_failure_indicators_are_binary_and_reproducible():
    district, models, world = setup()
    assets = list(world.assets.values())
    na = len(assets)
    rain = np.exp(np.random.default_rng(1).normal(0, 0.4, size=(5, na)))
    u = np.random.default_rng(2).random((na, 5))
    ind1 = failure_indicators(assets, models, rain, u)
    ind2 = failure_indicators(assets, models, rain, u)
    assert ind1.shape == (na, N_OPTIONS, 5)
    assert ind1.dtype == bool
    assert np.array_equal(ind1, ind2)


def test_network_aware_objective_prefers_repair():
    district, models, world = setup()
    assets = list(world.assets.values())
    na = len(assets)
    rain = np.exp(np.random.default_rng(3).normal(0, 0.4, size=(8, na)))
    u = np.random.default_rng(4).random((na, 8))
    obj = network_aware_objective(assets, models, rain, u, budget=1e6, crew=1e6)

    x_none = np.zeros(na * N_OPTIONS)
    x_none[0::N_OPTIONS] = 1.0  # every asset -> NONE
    x_replace = np.zeros(na * N_OPTIONS)
    x_replace[N_OPTIONS - 1::N_OPTIONS] = 1.0  # every asset -> REPLACE
    assert obj(x_replace) <= obj(x_none) + 1e-9


def test_optimizer_policies_respect_budget():
    district, models, world = setup()
    assets = list(world.assets.values())
    na = len(assets)
    rain = np.exp(np.random.default_rng(5).normal(0, 0.4, size=(10, na)))
    ctx = PolicyContext(models.sor, district.budget_crore, district.crew_days)

    for policy in (AdditiveMilpPolicy(models, rain, seed=0),
                   NetworkAwarePolicy(models, rain, seed=0)):
        chosen = policy.propose(assets, ctx)
        spent = sum(
            models.sor.cost(world.assets[aid].structure_type, opt)
            for aid, opt in chosen.items()
        )
        assert spent <= district.budget_crore + 1e-6
        assert all(opt.value != "none" for opt in chosen.values())
