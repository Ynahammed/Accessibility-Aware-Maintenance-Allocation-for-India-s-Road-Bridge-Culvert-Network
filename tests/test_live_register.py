"""Tests for the live register that planning and simulation actually use.

The loader's rules are tested in ``test_pwd_reply.py``; here the question is whether a
**validated** reply changes the numbers a plan or simulation produces, and whether an
absent or untrustworthy file leaves the defaults untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import rra.app.register as register_module
from rra.app.lab import _run_experiment, normalize_params
from rra.app.register import apply_payload, live_register
from rra.assumptions import AssumptionRegister
from rra.cost.interventions import Intervention, apply_effect
from rra.pipeline import build_models
from rra.network.synthetic import make_district


def _payload(**overrides) -> dict:
    payload = {
        "generated_utc": "2026-11-20T06:00:00+00:00",
        "manifest": {
            "office": "EE PWD (Bridges), Alappuzha",
            "application_ref": "PWD/ALP/RTI/2026/123",
            "reply_date": "2026-11-20",
        },
        "register": {
            "outage_mean_days_culvert": {
                "value": 44.5,
                "source": "fitted",
                "provenance": {"n": 6, "statistic": "median", "table": "closures", "page": "4"},
            },
            "repair_effect_minor": {
                "value": 2.0,
                "source": "fitted",
                "provenance": {"n": 6, "statistic": "median", "table": "inspections"},
            },
            "emergency_premium": {
                "value": 1.75,
                "source": "fitted",
                "provenance": {"n": 6, "statistic": "median-ratio", "table": "expenditure"},
            },
        },
        "schedule_of_rates": {
            "culvert": {
                "value": 0.0205,
                "source": "fitted",
                "provenance": {"n": 6, "table": "sor"},
            }
        },
        "labour_days": {
            "culvert": {"value": 7.0, "source": "fitted", "provenance": {"n": 6}}
        },
    }
    payload.update(overrides)
    return payload


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / register_module.OVERRIDES_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    """A project root whose only file is the loader output (initially absent)."""
    monkeypatch.setattr(register_module, "ROOT", tmp_path)
    register_module.cache_clear()
    yield tmp_path
    register_module.cache_clear()


# --- fallback behaviour --------------------------------------------------------------


def test_missing_override_file_keeps_every_default(project_root):
    live = live_register()

    assert live.measured is False
    assert live.fingerprint == "default"
    assert live.applied == {}
    assert live.register.point_values() == AssumptionRegister.default().point_values()
    assert "placeholder" in live.sor.source
    assert live.describe()["source"] == "default"


def test_corrupt_file_keeps_defaults_and_reports_a_warning(project_root):
    path = project_root / register_module.OVERRIDES_RELPATH
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    live = live_register()
    assert live.measured is False
    assert live.register["outage_mean_days_culvert"].default == 10.0
    assert live.warnings and "defaults kept" in live.warnings[0]


def test_entry_without_provenance_keeps_the_assumption():
    payload = _payload()
    payload["manifest"] = {}  # no application reference anywhere
    live = apply_payload(payload)

    assert "outage_mean_days_culvert" not in live.applied
    assert live.register["outage_mean_days_culvert"].default == 10.0
    assert any("no provenance" in w for w in live.warnings)


def test_unknown_parameter_and_bad_values_are_ignored_with_warnings():
    payload = _payload()
    payload["register"]["not_a_parameter"] = {"value": 1.0, "source": "fitted"}
    payload["register"]["repair_effect_replace"] = {"value": "many", "source": "fitted"}
    payload["register"]["fragility_beta0"] = {"value": float("nan"), "source": "fitted"}

    live = apply_payload(payload)

    assert "not_a_parameter" not in live.applied
    assert "repair_effect_replace" not in live.applied
    assert live.register["repair_effect_replace"].default == 4.0
    assert live.register["fragility_beta0"].default == -3.0
    joined = " | ".join(live.warnings)
    assert "unknown register parameter" in joined
    assert "not a finite number" in joined


def _refused_payload() -> dict:
    payload = _payload()
    payload["skipped"] = [
        {"parameter": "base_cost::major_bridge", "reason": "implausible_magnitude",
         "median_rate_crore": 35.0, "base_cost_crore": 8.75, "placeholder_crore": 0.25,
         "ratio_to_placeholder": 35.0, "n": 6,
         "hint": "rates must be in Rs crore, not Rs lakh/rupees; the rate was not applied"},
        {"parameter": "labour_days::major_bridge", "reason": "implausible_magnitude", "n": 6},
        {"parameter": "outage_mean_days_major_bridge", "reason": "fewer_than_min_n",
         "n": 0, "required": 5},
    ]
    payload["coverage"] = {
        "structures": {"unmapped_types": ["causeway"]},
        "inspections": {"refused_unstated_scale_or_unparseable": 2},
        "expenditure": {"unmapped_work_types": ["road furniture"]},
        "repair_pairs": {"worsened": 1, "unadjudicated": 3},
        "schedule_of_rates": {"rejected_implausible": [
            {"structure_type": "major_bridge", "intervention": "major",
             "ratio_to_placeholder": 35.0, "placeholder_crore": 0.25},
        ]},
    }
    return payload


def test_refused_overrides_are_surfaced_with_their_reasons():
    """A partly refused reply must not look like a clean one in the assumptions payload."""
    live = apply_payload(_refused_payload())

    assert [r["parameter"] for r in live.refused] == [
        "base_cost::major_bridge", "labour_days::major_bridge",
        "outage_mean_days_major_bridge",
    ]
    cost = live.refused[0]
    assert cost["label"] == "base cost, major bridge"
    assert cost["reason_label"] == "implausible magnitude"
    assert "8.75 cr" in cost["detail"] and "35×" in cost["detail"]
    assert "Rs crore" in cost["detail"]  # the loader's unit hint survives
    assert live.refused[1]["reason_label"] == "implausible magnitude"
    assert "no crew days derived" in live.refused[1]["detail"]
    assert live.refused[2]["reason_label"] == "sample too small"
    assert live.refused[2]["detail"] == "n=0 of 5 required"

    warnings = " | ".join(live.coverage_warnings)
    assert "unmapped: causeway" in warnings
    assert "2 inspection row(s) refused" in warnings
    assert "road furniture" in warnings
    assert "contradict the repair" in warnings
    assert "no pre-work history" in warnings
    # the rejected SoR entry is already shown as a refused override, not counted twice
    assert "major bridge major rate refused" not in warnings

    assert live.describe()["refused"] == 3
    assert live.describe()["coverage_warnings"] == len(live.coverage_warnings)
    assert "3 override(s) were refused" in live.markdown()
    # the affected row still shows the placeholder, not a silently applied value
    assert live.sor.base_cost_crore["major_bridge"] == pytest.approx(0.25)


def test_no_reply_means_nothing_to_report():
    live = apply_payload({})
    assert live.refused == () and live.coverage_warnings == ()
    assert live.describe()["refused"] == 0
    assert "refused" not in live.markdown()


def test_unknown_structure_type_and_nonpositive_rate_are_ignored():
    payload = _payload()
    payload["schedule_of_rates"]["pier"] = {"value": 0.5}
    payload["schedule_of_rates"]["minor_bridge"] = {"value": 0.0}

    live = apply_payload(payload)
    assert "pier" not in live.rates
    assert "minor_bridge" not in live.rates
    assert live.sor.base_cost_crore["minor_bridge"] == pytest.approx(0.08)  # placeholder kept
    assert any("unknown structure type" in w for w in live.warnings)


# --- applying a valid reply ----------------------------------------------------------


def test_valid_reply_changes_the_register_and_the_schedule_of_rates():
    live = apply_payload(_payload())

    culvert = live.register["outage_mean_days_culvert"]
    assert culvert.default == pytest.approx(44.5)
    assert culvert.low == pytest.approx(3.0)
    assert culvert.high == pytest.approx(44.5)  # widened, never clipped
    assert culvert.source == "fitted"
    assert "RTI PWD/ALP/RTI/2026/123" in culvert.how

    assert live.register["repair_effect_minor"].default == pytest.approx(2.0)
    assert live.register["emergency_premium"].default == pytest.approx(1.75)

    assert live.sor.cost("culvert", Intervention.MINOR) == pytest.approx(0.0205)
    assert live.sor.cost("culvert", Intervention.MAJOR) == pytest.approx(0.0205 * 4)
    assert live.sor.labour("culvert", Intervention.MINOR) == pytest.approx(7.0)
    # an untouched type keeps its placeholder
    assert live.sor.base_cost_crore["major_bridge"] == pytest.approx(0.25)


def test_provenance_is_preserved_for_each_applied_value():
    live = apply_payload(_payload())
    record = live.applied["outage_mean_days_culvert"]

    assert record["value"] == pytest.approx(44.5)
    assert record["source"] == "fitted"
    assert record["provenance"]["application_ref"] == "PWD/ALP/RTI/2026/123"
    assert record["provenance"]["office"].startswith("EE PWD")
    assert record["provenance"]["reply_date"] == "2026-11-20"
    assert record["provenance"]["n"] == 6
    assert record["provenance"]["table"] == "closures"
    assert record["provenance"]["page"] == "4"
    assert record["previous"] == {"default": 10.0, "source": "assumed"}

    described = live.describe()
    assert described["source"] == "pwd_rti"
    assert described["application_ref"] == "PWD/ALP/RTI/2026/123"
    assert "outage_mean_days_culvert" in described["parameters"]


def test_markdown_is_rendered_from_the_live_values_and_names_the_reply():
    live = apply_payload(_payload())
    md = live.markdown()

    # measured values, not the default-register table
    assert "| `outage_mean_days_culvert` | days | 3–44.5 | 44.5 | fitted |" in md
    assert "| `outage_mean_days_culvert` | days | 3–30 | 10 | assumed |" not in md
    assert "PWD/ALP/RTI/2026/123" in md
    assert "EE PWD (Bridges), Alappuzha" in md
    assert "2026-11-20" in md
    # the preamble describes the register in force, not the default-register document
    assert "The register in force" in md
    assert "Every entry is an **assumed**" not in md
    assert "recorded separately in `docs/assumptions_measured.md`" not in md
    # untouched parameters stay visibly assumed
    assert "| `outage_mean_days_major_bridge` |" in md and "assumed" in md


def test_markdown_without_a_reply_makes_no_provenance_claim():
    md = apply_payload({}).markdown()
    assert "Live register" not in md
    assert "| `outage_mean_days_culvert` | days | 3–30 | 10 | assumed |" in md
    # the default register keeps the document preamble used by docs/assumptions.md
    assert "Every entry is an **assumed**" in md
    assert "The register in force" not in md


def test_rerunning_the_loader_is_picked_up_without_a_restart(project_root):
    path = _write(project_root, _payload())
    first = live_register()
    assert first.register["outage_mean_days_culvert"].default == pytest.approx(44.5)
    fingerprint = first.fingerprint

    payload = _payload()
    payload["register"]["outage_mean_days_culvert"]["value"] = 30.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    second = live_register()
    assert second.register["outage_mean_days_culvert"].default == pytest.approx(30.0)
    assert second.fingerprint != fingerprint


# --- the override must reach the models the simulator uses --------------------------


def _district(seed: int = 0):
    return make_district(n_junctions=24, n_habitations=14, n_structures=10, seed=seed)


def test_models_take_outage_days_premium_effects_and_prices_from_the_live_register():
    live = apply_payload(_payload())
    district = _district()
    models = build_models(district, live.register, sor=live.sor)
    culvert_assets = [aid for aid, _, s_type in district.structures if s_type == "culvert"]
    bridge_assets = [aid for aid, _, s_type in district.structures if s_type == "minor_bridge"]
    assert culvert_assets and bridge_assets

    assert models.premium == pytest.approx(1.75)
    assert all(models.outage_days[aid] == pytest.approx(44.5) for aid in culvert_assets)
    # an unmeasured type keeps its own assumption, not the culvert value
    assert all(models.outage_days[aid] == pytest.approx(30.0) for aid in bridge_assets)
    assert models.effect(Intervention.MINOR).condition_reset == pytest.approx(2.0)
    assert models.effect(Intervention.MINOR).fragility_factor == pytest.approx(
        pytest.importorskip("math").exp(-0.35 * 2.0)
    )
    assert models.sor.cost("culvert", Intervention.MINOR) == pytest.approx(0.0205)


def test_repair_effect_changes_the_condition_after_repair():
    default_models = build_models(_district(), AssumptionRegister.default())
    live = apply_payload(_payload())
    measured_models = build_models(_district(), live.register, sor=live.sor)

    assert apply_effect(2, default_models.effect(Intervention.MINOR)) == 2  # 2 - 0.5 -> 2
    assert apply_effect(2, measured_models.effect(Intervention.MINOR)) == 0  # measured reset of 2
    assert (
        measured_models.effect(Intervention.MINOR).fragility_factor
        < default_models.effect(Intervention.MINOR).fragility_factor
    )


def test_paired_experiment_spend_follows_the_measured_schedule_of_rates():
    params = normalize_params(
        {"preset": "redundant", "redundancy": 2, "scenarios": 2, "years": 1, "budget_crore": 0.4}
    )
    baseline = _run_experiment(params, register_module.apply_payload({}))
    measured = _run_experiment(params, apply_payload(_payload()))

    base_culvert = next(p for p in baseline["policies"] if p["policy"] == "network_aware")
    live_rows = next(p for p in measured["policies"] if p["policy"] == "network_aware")
    assert base_culvert["mean_planned_crore"] != pytest.approx(live_rows["mean_planned_crore"])
    assert measured["register"]["source"] == "pwd_rti"
    assert baseline["register"]["source"] == "default"
    # the paired comparison stays paired: same scenario count in both runs
    assert measured["comparison"]["n_scenarios"] == baseline["comparison"]["n_scenarios"]
