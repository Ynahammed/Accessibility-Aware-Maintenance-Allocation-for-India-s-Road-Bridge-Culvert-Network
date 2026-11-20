"""Tests for the demo server API (pure functions; no sockets needed).

The demo must never drift from the research code it wraps: these tests call the same
``run_experiment`` / ``run_loss`` / ``load_evidence`` functions the HTTP handler uses.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))

import server as demo  # noqa: E402


def test_assumptions_payload_is_identical_on_both_transports():
    """The stdlib demo server must not 404 where FastAPI answers."""
    from fastapi.testclient import TestClient

    from rra.api import app

    served = TestClient(app).get("/api/assumptions")
    assert served.status_code == 200
    payload = served.json()
    # demo/server.py re-exports the handler's own builder, so the objects are equal
    assert demo.assumptions_payload() == payload
    assert payload["ok"] is True
    assert len(payload["parameters"]) == 21
    assert payload["source"]["source"] in {"default", "pwd_rti"}
    assert "| Parameter |" in payload["register_markdown"]


def test_stdlib_http_route_answers_where_fastapi_does(monkeypatch):
    """Exercise the real socket route, not just the shared payload builder.

    The stdlib handler is what ``python demo/server.py`` runs, so a missing branch in
    ``_handle`` would 404 in the browser while the FastAPI test above still passed.
    """
    from fastapi.testclient import TestClient

    from rra.api import app

    expected = TestClient(app).get("/api/assumptions").json()
    monkeypatch.setattr(demo.DemoHandler, "log_message", lambda *a, **k: None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), demo.DemoHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        for path in ("/api/assumptions", "/api/assumptions/"):
            with urllib.request.urlopen(base + path, timeout=10) as response:
                assert response.status == 200
                body = json.loads(response.read().decode("utf-8"))
            assert body == expected
            assert body["source"]["source"] in {"default", "pwd_rti"}
            assert {"source", "parameters", "fingerprint"} <= set(body["source"])
    finally:
        httpd.shutdown()
        httpd.server_close()


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
    # The active evidence base is Indian only; US NBI results are archived, not served.
    assert "e1_deterioration" not in ev
    assert ev["flood_exposure"]["hazard"]["scenarios"]
    assert len(ev["flood_exposure"]["hazard"]["scenarios"]) == 12
    assert ev["access_baseline"]["population_views"]
    assert ev["e3_allocation"]["policies"]
    assert ev["e4_network_effects"]["by_redundancy"]
    assert "benefit_cost" in ev["e8_robustness"]["win_rate"]
    comparison = ev["real_district_comparison"]["districts"]
    assert [row["district"] for row in comparison] == ["Alappuzha", "Pathanamthitta"]
    assert [round(row["condition_first_minus_random_person_days"], 1) for row in comparison] == [-4096.3, -4335.3]
    for row, source in zip(comparison, (
        "experiments/e09_alappuzha_real/results.json",
        "experiments/e11_pathanamthitta_real/results.json",
    )):
        assert row["n_scenarios"] == 40
        assert row["source"]["file"] == source
        assert row["source"]["fields"]["paired_sd_person_days"].startswith("robustness.precision")
        assert row["source"]["interval_method"].startswith("Student t interval")
    assert set(comparison[0]) == {
        "district", "n_scenarios", "condition_first_minus_random_person_days",
        "paired_sd_person_days", "condition_first_better_scenarios",
        "additive_gain_vs_condition_first_person_days", "paired_95_ci_person_days", "source",
    }
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
