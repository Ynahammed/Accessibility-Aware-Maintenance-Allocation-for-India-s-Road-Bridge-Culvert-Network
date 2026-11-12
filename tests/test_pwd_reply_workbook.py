"""End-to-end ingest of a realistic (XLSX) RTI reply workbook.

The other loader tests build their CSVs in the test body, so the XLSX path — sheet
selection, human column headers, mixed numeric/text ratings, a still-closed structure and a
major-only Schedule of Rates — was never exercised. This fixture is a small but realistic
reply in that shape: 13 structures, 36 inspections, 11 closures, 18 expenditure rows and 15
SoR items across three sheets.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rra.assumptions import AssumptionRegister
from rra.ingest.pwd_reply import derive, effective_register, load_reply, write_outputs

pytest.importorskip("openpyxl", reason="the reply fixture is an XLSX workbook")

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "pwd_reply_alappuzha_2026"
ROOT = Path(__file__).resolve().parents[1]


def _derived(tmp_path: Path):
    manifest, tables = load_reply(FIXTURE)
    register = AssumptionRegister.default()
    return manifest, derive(manifest, tables, register), register


def test_workbook_supplies_the_register_rates_and_labour_values(tmp_path):
    manifest, ov, register = _derived(tmp_path)

    assert manifest["application_ref"] == "PWD/ALP/RTI/2026/123"
    # the fixture must not be mistaken for an actual RTI response
    assert manifest["sample"] is True and "not an RTI response" in manifest["note"]
    assert set(ov.coverage) >= {
        "structures", "inspections", "closures", "expenditure", "schedule_of_rates"
    }

    # register: culvert outages (7 rows, median 45 d), both repair effects, the premium
    assert ov.register["outage_mean_days_culvert"].value == pytest.approx(45.0)
    assert ov.register["outage_mean_days_culvert"].provenance.n == 7
    # five culverts at Fair (2) read Good (0) after the repair, so the raw gain is two
    # steps. Adding the ~1.06-year gap's deterioration would give ≈3.07, but a structure
    # can recover at most the condition it had (0 is the floor), so the pair is capped at 2.
    assert ov.register["repair_effect_minor"].value == pytest.approx(2.0)
    assert ov.register["repair_effect_minor"].provenance.n == 5
    assert ov.register["repair_effect_major"].value == pytest.approx(2.0)
    assert ov.register["repair_effect_major"].provenance.n == 6
    pairs = ov.coverage["repair_pairs"]
    assert pairs["capped"] == 12  # every pair reads Good afterwards
    assert pairs["cap_rule"] == "adjusted recovery capped at the pre-work condition"
    assert {p["used"] for p in pairs["capped_pairs"]} == {2}
    assert all(p["adjusted_uncapped"] > p["before"] for p in pairs["capped_pairs"])
    assert ov.register["emergency_premium"].value == pytest.approx(1.75)
    assert ov.register["emergency_premium"].provenance.n == 6
    for name in ("outage_mean_days_culvert", "repair_effect_minor", "emergency_premium"):
        assert ov.register[name].previous["source"] == "assumed"
        assert ov.register[name].source == "fitted"
    minor_detail = ov.register["repair_effect_minor"].provenance.detail
    assert "net of observed pre-work deterioration" in minor_detail
    assert "understated" in minor_detail and "overstated" in minor_detail
    assert "capped at the pre-work condition" in minor_detail

    # a group below MIN_SAMPLE, and a single replacement, stay as assumptions
    skipped = {s["parameter"]: s for s in ov.skipped}
    assert skipped["outage_mean_days_minor_bridge"]["reason"] == "fewer_than_min_n"
    assert skipped["outage_mean_days_minor_bridge"]["n"] == 3
    assert skipped["repair_effect_replace"]["n"] == 1
    assert "repair_effect_replace" not in ov.register

    # Schedule of Rates: major bridge quotes major items only, so the base is divided by 4
    assert ov.rates["culvert"].value == pytest.approx(0.016)
    assert ov.rates["minor_bridge"].value == pytest.approx(0.054)
    assert ov.rates["major_bridge"].value == pytest.approx(0.085)
    assert "COST_MULTIPLIER[major]=4" in ov.rates["major_bridge"].provenance.detail

    # crew days come from the intervention that priced each type
    assert ov.labour["culvert"].value == pytest.approx(5.0)
    assert ov.labour["minor_bridge"].value == pytest.approx(22.0)
    assert ov.labour["major_bridge"].value == pytest.approx(28.8)  # 72 / 2.5
    assert ov.labour["major_bridge"].provenance.n == 5
    assert effective_register(register, ov)["outage_mean_days_culvert"].high == pytest.approx(45.0)

    # coverage: the causeway is reported and excluded, one closure is still open
    assert ov.coverage["structures"]["unmapped_types"] == ["causeway"]
    assert ov.coverage["structures"]["mapped_type"] == 12
    assert ov.coverage["closures"]["still_closed"] == 1
    pairs = ov.coverage["repair_pairs"]
    assert pairs["by_intervention"] == {"major": 6, "minor": 5, "replace": 1}
    assert pairs["worsened"] == 0


def test_loader_cli_runs_on_the_workbook_end_to_end(tmp_path):
    out = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ingest_pwd_reply.py"), str(FIXTURE),
         "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "tables read: closures, expenditure, inspections, sor, structures" in result.stdout
    assert "PWD/ALP/RTI/2026/123" in result.stdout
    # the applied labour overrides are part of the summary, not just the JSON
    assert "crew-days (base minor-repair labour, days)" in result.stdout
    assert "major_bridge   28.80" in result.stdout

    payload = json.loads((out / "register_overrides.json").read_text(encoding="utf-8"))
    assert payload["manifest"]["application_ref"] == "PWD/ALP/RTI/2026/123"
    assert payload["manifest"]["sample"] is True
    assert payload["register"]["outage_mean_days_culvert"]["value"] == pytest.approx(45.0)
    assert payload["register"]["outage_mean_days_culvert"]["provenance"]["office"].startswith(
        "Executive Engineer"
    )
    assert {k: round(v["value"], 4) for k, v in payload["schedule_of_rates"].items()} == {
        "culvert": 0.016, "minor_bridge": 0.054, "major_bridge": 0.085,
    }
    assert {k: round(v["value"], 2) for k, v in payload["labour_days"].items()} == {
        "culvert": 5.0, "minor_bridge": 22.0, "major_bridge": 28.8,
    }
    coverage = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    assert coverage["structures"]["unmapped_types"] == ["causeway"]
