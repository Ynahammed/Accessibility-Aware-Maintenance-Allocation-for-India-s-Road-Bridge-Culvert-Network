"""Tests for the demo server API (pure functions; no sockets needed).

The demo must never drift from the research code it wraps: these tests call the same
``run_experiment`` / ``run_loss`` / ``load_evidence`` functions the HTTP handler uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))

import server as demo  # noqa: E402


def test_normalize_clamps_bad_input():
    p = demo.normalize_params({"budget_crore": -5, "scenarios": 10_000, "seed": "x",
                               "preset": "evil", "redundancy": 99})
    assert p["budget_crore"] == 0.0
    assert p["scenarios"] == 32
    assert p["preset"] == "generic"
    assert p["redundancy"] == 4
    assert p["seed"] == 0  # unparseable falls back to default


def test_normalize_defaults_on_empty():
    p = demo.normalize_params({})
    assert p == demo.DEFAULTS


def test_run_experiment_generic_returns_paired_results():
    out = demo.run_experiment({"preset": "generic", "scenarios": 4, "years": 1,
                               "budget_crore": 0.6, "seed": 0})
    assert out["ok"] is True
    names = [r["policy"] for r in out["policies"]]
    assert names == list(demo.POLICY_ORDER)
    # do_nothing never plans anything; optimizers plan at least something
    by = {r["policy"]: r for r in out["policies"]}
    assert by["do_nothing"]["plan"] == {}
    assert by["worst_first"]["mean_person_days"] > 0
    # paired comparison present and shaped
    c = out["comparison"]
    assert c["n_scenarios"] == 4
    assert c["ci_lo"] <= c["mean"] <= c["ci_hi"]
    # map payload has structures with solo losses
    assert len(out["map"]["structures"]) == out["n_assets"] == 10
    assert all(s["solo_loss"] >= 0 for s in out["map"]["structures"])


def test_run_experiment_is_cached_and_deterministic():
    a = demo.run_experiment({"preset": "generic", "scenarios": 4, "years": 1, "seed": 1})
    b = demo.run_experiment({"preset": "generic", "scenarios": 4, "years": 1, "seed": 1})
    assert a is b  # same cache entry, identical numbers
    assert a["policies"] == b["policies"]


def test_run_experiment_redundant_preset():
    out = demo.run_experiment({"preset": "redundant", "redundancy": 2, "scenarios": 4,
                               "years": 1, "budget_crore": 0.4, "stress": 0.9})
    assert out["n_assets"] == 6  # 3 corridors × 2 routes
    by = {r["policy"]: r for r in out["policies"]}
    # at redundancy 2 every solo loss is zero => the additive MILP funds nothing
    assert by["additive_milp"]["plan"] == {}


def test_loss_explorer_non_additivity():
    # fail both structures of corridor 0 (S0, S1 at redundancy 2)
    out = demo.run_loss({"redundancy": 2, "failed": ["S0", "S1"], "seed": 0})
    assert out["ok"] is True
    # each alone is harmless (parallel route survives): solo loss = 0
    assert out["solo"]["S0"] == 0.0
    assert out["solo"]["S1"] == 0.0
    # but jointly they cut the corridor: set loss > sum of solos
    assert out["set_loss"] > 0
    assert out["set_loss"] > out["sum_solo"]
    assert out["corridor_of"]["S1"] == out["corridor_of"]["S0"]


def test_loss_empty_set_is_zero():
    out = demo.run_loss({"redundancy": 2, "failed": [], "seed": 0})
    assert out["set_loss"] == 0.0
    assert out["sum_solo"] == 0.0


def test_loss_rejects_unknown_structure():
    try:
        demo.run_loss({"redundancy": 2, "failed": ["S999"]})
    except ValueError as exc:
        assert "S999" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown structure")


def test_load_evidence_contains_frozen_results_and_register():
    ev = demo.load_evidence()
    assert ev["ok"] is True
    assert ev["e1_deterioration"]["n_panel_rows"] > 500_000  # real NBI scale
    models = {m["model"] for m in ev["e1_deterioration"]["models"]}
    assert {"M0_markov", "M1_gbm", "climatology"} <= models
    assert ev["e3_allocation"]["policies"]
    assert ev["e4_network_effects"]["by_redundancy"]
    assert "benefit_cost" in ev["e8_robustness"]["win_rate"]
    assert len(ev["assumptions"]) == 21
    assert {a["source"] for a in ev["assumptions"].values()} <= {"real", "fitted", "assumed"}
    assert any(r["status"] == "blocked" for r in ev["data_matrix"])


def test_fastapi_app_exposes_demo_routes():
    from app import app

    routes = {
        route.path: route.methods
        for route in app.routes
        if hasattr(route, "methods")
    }

    assert "/" in routes and "GET" in routes["/"]
    assert "/api/evidence" in routes and "GET" in routes["/api/evidence"]
    assert "/api/run" in routes and "POST" in routes["/api/run"]
    assert "/api/loss" in routes and "POST" in routes["/api/loss"]
