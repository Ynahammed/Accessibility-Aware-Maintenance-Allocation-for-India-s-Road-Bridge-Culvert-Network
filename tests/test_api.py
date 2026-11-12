"""Tests for the FastAPI product layer.

Everything runs against the application services, so a passing test means the endpoint
and the local demo server agree (they share ``rra.app``).
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import rra.app.evidence as evidence_module
import rra.app.register as register_module
from rra.api import app

client = TestClient(app)


def test_health_lists_policies_and_districts():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["n_districts"] >= 4
    assert "network_aware" in body["policies"]
    assert r.headers["cache-control"] == "no-store"


def test_districts_carry_provenance_and_status():
    body = client.get("/api/districts").json()
    by_id = {d["id"]: d for d in body["districts"]}
    assert {"synth-generic", "synth-redundant-r2", "alappuzha-osm"} <= set(by_id)
    generic = by_id["synth-generic"]
    assert generic["provenance"] == "synthetic"
    assert generic["status"] == "ready"
    assert generic["n_structures"] == 10
    assert by_id["alappuzha-osm"]["provenance"] == "real-osm"
    assert by_id["alappuzha-osm"]["status"] == "network-only"


def test_unknown_district_is_404():
    r = client.get("/api/districts/nowhere")
    assert r.status_code == 404
    assert "unknown district" in r.json()["detail"]


def test_assets_payload_has_service_state():
    r = client.get("/api/districts/synth-redundant-r2/assets")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    rows = body["assets"]
    assert len(rows) == body["district"]["n_structures"] == 6
    assert all(row["solo_loss"] == 0 for row in rows)  # parallel routes: additive sees nothing
    assert {row["corridor"] for row in rows} == {0, 1, 2}


def test_plan_respects_budget_and_crew():
    r = client.post(
        "/api/districts/synth-redundant-r3/plan",
        json={"budget_crore": 0.4, "seed": 0, "scenarios": 4, "years": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["budget_crore"] == 0.4
    assert body["planned_spend_crore"] <= body["budget_crore"] + 1e-9
    assert body["crew_days_used"] <= body["crew_days"] + 1e-9
    assert body["n_funded"] >= 1
    assert len(body["recommendations"]) == body["district"]["n_structures"]
    funded = [row for row in body["recommendations"] if row["funded"]]
    assert sum(row["cost_crore"] for row in funded) == pytest_approx(body["planned_spend_crore"])
    for row in body["recommendations"]:
        assert row["reason"]
        assert 0 <= row["condition_after"] <= 3
        assert 0 < row["fragility_factor"] <= 1.0


def pytest_approx(value):
    import pytest

    return pytest.approx(value)


def test_network_view_is_read_only_and_has_no_allocation_numbers():
    r = client.get("/api/districts/alappuzha-osm/network")
    assert r.status_code == 200
    body = r.json()
    assert body["read_only"] is True
    assert body["provenance"] == "real-osm"
    assert len(body["nodes"]) == body["counts"]["nodes"] == 1972
    assert len(body["edges"]) == body["counts"]["edges"] == 2361
    assert sum(1 for e in body["edges"] if e["bridge"]) == body["counts"]["bridges"] == 74
    assert body["counts"]["culverts"] == 0
    # read-only means exactly that: no cost, condition, loss or recommendation fields
    for forbidden in ("recommendations", "loss", "planned_spend_crore", "n_funded"):
        assert forbidden not in body


def test_network_view_for_synthetic_district_is_geometric_only():
    body = client.get("/api/districts/synth-redundant-r2/network").json()
    assert body["read_only"] is False
    assert body["counts"]["nodes"] == len(body["nodes"])
    assert body["counts"]["edges"] == len(body["edges"]) > 0
    assert not any(e["bridge"] for e in body["edges"])
    assert body["district"]["n_structures"] == 6  # the plan stays the allocation view


def test_plan_on_network_only_district_is_400():
    r = client.post("/api/districts/alappuzha-osm/plan", json={})
    assert r.status_code == 400
    assert "no allocation layer" in r.json()["detail"]


def test_consequence_reports_non_additivity():
    r = client.post(
        "/api/districts/synth-redundant-r2/consequence",
        json={"failed": ["S0", "S1"], "seed": 0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sum_solo"] == 0.0
    assert body["set_loss"] > 0.0
    assert body["corridor_of"]["S0"] == body["corridor_of"]["S1"] == 0


def test_consequence_rejects_unknown_structure():
    r = client.post(
        "/api/districts/synth-redundant-r2/consequence", json={"failed": ["S999"]}
    )
    assert r.status_code == 400
    assert "S999" in r.json()["detail"]


def test_simulate_endpoint_is_paired_and_cacheable():
    body = {
        "budget_crore": 0.4,
        "stress": 0.9,
        "seed": 0,
        "scenarios": 2,
        "years": 1,
    }
    r1 = client.post("/api/districts/synth-redundant-r2/simulate", json=body)
    r2 = client.post("/api/districts/synth-redundant-r2/simulate", json=body)
    assert r1.status_code == 200
    assert r1.json() == r2.json()  # deterministic + cached
    out = r1.json()
    assert [p["policy"] for p in out["policies"]] == [
        "do_nothing",
        "worst_first",
        "benefit_cost",
        "additive_milp",
        "network_aware",
    ]
    assert out["comparison"]["n_scenarios"] == 2


def test_evidence_and_assumptions_expose_the_live_register(tmp_path, monkeypatch):
    root = tmp_path / "project"
    output = root / "data" / "processed" / "pwd_reply" / "register_overrides.json"
    output.parent.mkdir(parents=True)
    output.write_text(
        json.dumps(
            {
                "manifest": {"office": "EE PWD", "application_ref": "RTI/123"},
                "register": {
                    "outage_mean_days_culvert": {
                        "value": 44.5,
                        "source": "fitted",
                        "provenance": {"table": "closures", "n": 6},
                    }
                },
                "skipped": [
                    {
                        "parameter": "repair_effect_minor",
                        "reason": "fewer_than_min_n",
                        "n": 1,
                        "required": 5,
                    }
                ],
                "coverage": {"structures": {"unmapped_types": ["causeway"]}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(register_module, "ROOT", root)
    monkeypatch.setattr(evidence_module, "_EVIDENCE_CACHE", None)
    register_module.cache_clear()
    try:
        evidence = evidence_module.get_evidence()
        assert set(evidence["assumption_overrides"]) == {"outage_mean_days_culvert"}
        applied = evidence["assumption_overrides"]["outage_mean_days_culvert"]
        assert applied["value"] == 44.5
        assert applied["provenance"]["application_ref"] == "RTI/123"
        assert evidence["assumptions_source"]["source"] == "pwd_rti"
        assert evidence["assumptions"]["outage_mean_days_culvert"]["source"] == "fitted"

        # The rendered markdown must show the measured value and name the reply, so it
        # cannot contradict the parameters in the same payload.
        markdown = evidence["register_markdown"]
        assert "44.5" in markdown and "RTI/123" in markdown
        assert "| `outage_mean_days_culvert` | days | 3–30 | 10 | assumed |" not in markdown
        # the field is not the default-register document text with measured rows spliced in
        assert "The register in force" in markdown
        assert "Every entry is an **assumed**" not in markdown

        # The dashboard-facing assumptions endpoint reads the same live register.
        params = client.get("/api/assumptions").json()
        assert params["parameters"]["outage_mean_days_culvert"]["default"] == 44.5
        assert params["parameters"]["outage_mean_days_culvert"]["high"] == 44.5
        assert params["source"]["application_ref"] == "RTI/123"
        assert params["register_markdown"] == markdown  # one source of truth
        # a refused override is visible in the payload, not silently omitted
        assert [r["parameter"] for r in params["refused"]] == ["repair_effect_minor"]
        assert params["refused"][0]["reason_label"] == "sample too small"
        assert params["coverage_warnings"] == [
            "1 structure type(s) excluded as unmapped: causeway"
        ]
        assert evidence["refused"] == params["refused"]
        assert evidence["coverage_warnings"] == params["coverage_warnings"]

        # Change the loader output after evidence was cached; the next request sees it
        # without reloading frozen experiment data.
        frozen_result = evidence["e4_network_effects"]
        output.write_text(
            '{"manifest":{"application_ref":"RTI/456"},'
            '"register":{"repair_effect_minor":{"value":2,"source":"fitted"}}}',
            encoding="utf-8",
        )
        refreshed = evidence_module.get_evidence()
        assert set(refreshed["assumption_overrides"]) == {"repair_effect_minor"}
        assert refreshed["assumption_overrides"]["repair_effect_minor"]["value"] == 2
        assert refreshed["e4_network_effects"] is frozen_result
    finally:
        register_module.cache_clear()
        monkeypatch.setattr(evidence_module, "_EVIDENCE_CACHE", None)


def test_assumptions_and_evidence_endpoints():
    a = client.get("/api/assumptions").json()
    assert len(a["parameters"]) == 21
    assert all(p["source"] in {"real", "fitted", "assumed"} for p in a["parameters"].values())

    ev = client.get("/api/evidence").json()
    assert ev["ok"] is True
    assert ev["e4_network_effects"]["by_redundancy"]
    assert isinstance(ev["assumption_overrides"], dict)
    assert isinstance(ev["refused"], list) and isinstance(ev["coverage_warnings"], list)
    assert isinstance(a["refused"], list) and isinstance(a["coverage_warnings"], list)
    assert any(row["status"] == "blocked" for row in ev["data_matrix"])


def test_legacy_lab_endpoints_still_work():
    run = client.post(
        "/api/run",
        json={"preset": "redundant", "redundancy": 2, "scenarios": 2, "years": 1},
    ).json()
    assert run["ok"] is True and run["n_assets"] == 6

    loss = client.post("/api/loss", json={"redundancy": 2, "failed": ["S0", "S1"]}).json()
    assert loss["ok"] is True and loss["set_loss"] > 0


def test_ui_is_served_at_root():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Accessibility-Aware Maintenance Allocation" in r.text


def test_request_validation_rejects_out_of_range():
    r = client.post("/api/run", json={"scenarios": 10_000})
    assert r.status_code == 422
