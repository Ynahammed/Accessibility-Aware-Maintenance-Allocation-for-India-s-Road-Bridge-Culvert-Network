"""Tests for the E4 factorial: the series (chain) topology and one tiny cell."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from rra import pipeline
from rra.assumptions import AssumptionRegister
from rra.network.build import class_speeds_from_register
from rra.network.synthetic import make_chain_district

ROOT = Path(__file__).resolve().parents[1]


def _chain(redundancy: int, n_segments: int = 3):
    register = AssumptionRegister.default()
    district = make_chain_district(
        n_segments=n_segments,
        redundancy=redundancy,
        seed=0,
        class_speeds=class_speeds_from_register(register),
    )
    return district, register


def test_chain_has_one_structure_per_route():
    district, _ = _chain(2)
    assert len(district.structures) == 3 * 2
    assert len(district.habitations) == 3
    assert len({aid for aid, _, _ in district.structures}) == 6


def test_chain_solo_loss_is_zero_with_parallel_routes():
    district, register = _chain(2)
    models = pipeline.build_models(district, register, seed=0)
    for _, node, _ in district.structures:
        assert models.acc.loss(failed_nodes=[node]) == 0.0


def test_chain_single_route_is_a_series_network():
    district, register = _chain(1)
    models = pipeline.build_models(district, register, seed=0)
    solo = [models.acc.loss(failed_nodes=[node]) for _, node, _ in district.structures]
    assert all(s >= 0 for s in solo)
    assert any(s > 0 for s in solo)  # r=1: a failure really does cut someone off


def test_failing_every_route_of_the_first_section_cuts_every_habitation():
    district, register = _chain(2)
    models = pipeline.build_models(district, register, seed=0)
    first_section = [node for aid, node, _ in district.structures if int(aid[1:]) < 2]
    assert models.acc.loss(failed_nodes=first_section) > 0


def _factorial_module():
    path = ROOT / "experiments" / "e04_network_effects" / "factorial.py"
    spec = importlib.util.spec_from_file_location("e04_factorial", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_factorial_cell_smoke():
    module = _factorial_module()
    cfg = dict(module.DEFAULTS)
    cfg.update(scenarios=2, years=1, optimizer_samples=2)
    cell = module.run_cell("chain", 2, 0.6, 1.2, cfg)

    assert cell["family"] == "chain"
    assert cell["n_assets"] == 8  # 4 sections x 2 routes
    assert {"do_nothing", "worst_first", "additive_milp", "network_aware"} <= set(
        cell["policies"]
    )
    paired = cell["paired"]["network_vs_worst_first"]
    assert paired["lo"] <= paired["mean"] <= paired["hi"]
    assert cell["budget_crore"] == 0.6
