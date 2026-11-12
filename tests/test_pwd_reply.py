import json
from pathlib import Path

import pandas as pd
import pytest

from rra.assumptions import AssumptionRegister
from rra.ingest.pwd_reply import (
    MAX_COST_RATIO,
    MIN_SAMPLE,
    ReplyError,
    derive,
    effective_register,
    load_reply,
    measured_markdown,
    write_outputs,
)


def _write_reply(folder: Path, *, include_ref: bool = True, numeric_scale: str | None = None) -> Path:
    """A small but complete reply: closures, inspections, expenditure, SoR."""
    folder.mkdir(parents=True, exist_ok=True)

    manifest = {
        "office": "EE PWD (Bridges), Alappuzha",
        "application_ref": "PWD/ALP/RTI/2026/123",
        "reply_date": "2026-11-20",
        "tables": {
            "structures": "structures.csv",
            "inspections": "inspections.csv",
            "closures": "closures.csv",
            "expenditure": "expenditure.csv",
            "sor": "sor.csv",
        },
    }
    if not include_ref:
        manifest.pop("application_ref")
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    structures = [
        {"structure_id": f"S{i}", "structure_type": "culvert"} for i in range(1, 7)
    ] + [{"structure_id": "B1", "structure_type": "minor bridge"}]
    pd.DataFrame(structures).to_csv(folder / "structures.csv", index=False)

    # culvert outages: median 45 days, which sits *above* the register's assumed 3-30 range
    culvert_days = [40, 42, 45, 48, 50, 44]
    rows = [
        {
            "structure_id": f"S{i}",
            "structure_type": "culvert",
            "closed_date": "2021-05-01",
            "reopened_date": (pd.Timestamp("2021-05-01") + pd.Timedelta(days=d)).date().isoformat(),
        }
        for i, d in enumerate(culvert_days, start=1)
    ]
    rows += [
        {
            "structure_id": "B1",
            "structure_type": "minor bridge",
            "closed_date": "2021-05-01",
            "reopened_date": (pd.Timestamp("2021-05-01") + pd.Timedelta(days=d)).date().isoformat(),
        }
        for d in (25, 30, 35)  # only 3: below the minimum sample
    ]
    rows.append(  # unusable rows must be dropped and counted, not repaired
        {"structure_id": "S1", "structure_type": "culvert", "closed_date": "not a date",
         "reopened_date": "2021-05-02"}
    )
    rows.append(  # negative duration must be excluded, not taken as a zero-day outage
        {"structure_id": "S2", "structure_type": "culvert", "closed_date": "2021-05-10",
         "reopened_date": "2021-05-01"}
    )
    pd.DataFrame(rows).to_csv(folder / "closures.csv", index=False)

    # inspections: minor repair in mid-2020 recovers two condition steps on five structures
    ins = []
    for i in range(1, 6):
        ins += [
            {"structure_id": f"S{i}", "inspection_date": "2020-01-05", "rating": "Poor",
             "rating_scheme": "text"},
            {"structure_id": f"S{i}", "inspection_date": "2021-01-05", "rating": "Good",
             "rating_scheme": "text"},
        ]
    ins += [
        {"structure_id": "S6", "inspection_date": "2020-01-05", "rating": 3,
         "rating_scheme": numeric_scale or "1-4"},
        {"structure_id": "S6", "inspection_date": "2021-01-05", "rating": 2,
         "rating_scheme": numeric_scale or "1-4"},
    ]
    pd.DataFrame(ins).to_csv(folder / "inspections.csv", index=False)

    exp = [
        {"structure_id": f"S{i}", "work_type": "minor repair", "completed_date": "2020-06-01",
         "spent_crore": 0.021, "estimate_crore": 0.02}
        for i in range(1, 7)
    ]
    ratios = (1.5, 1.6, 1.7, 1.8, 1.9, 2.0)
    exp += [
        {"structure_id": f"S{i}", "work_type": "emergency restoration",
         "completed_date": "2021-07-01", "spent_crore": 0.02 * r, "estimate_crore": 0.02}
        for i, r in enumerate(ratios, start=1)
    ]
    pd.DataFrame(exp).to_csv(folder / "expenditure.csv", index=False)

    sor = [
        {"item": f"culvert item {i}", "structure_type": "culvert", "intervention": "minor",
         "rate_crore": 0.018 + 0.001 * i}
        for i in range(6)
    ]
    pd.DataFrame(sor).to_csv(folder / "sor.csv", index=False)
    return folder


def test_reply_without_provenance_is_refused(tmp_path):
    folder = _write_reply(tmp_path / "reply", include_ref=False)
    with pytest.raises(ReplyError, match="application_ref"):
        load_reply(folder)


def test_missing_required_column_is_named(tmp_path):
    folder = _write_reply(tmp_path / "reply")
    df = pd.read_csv(folder / "closures.csv").drop(columns=["reopened_date"])
    df.to_csv(folder / "closures.csv", index=False)
    with pytest.raises(ReplyError, match="reopened_date"):
        load_reply(folder)


def test_outage_median_replaces_assumption_and_widens_range(tmp_path):
    folder = _write_reply(tmp_path / "reply")
    manifest, tables = load_reply(folder)
    reg = AssumptionRegister.default()
    ov = derive(manifest, tables, reg)

    culvert = ov.register["outage_mean_days_culvert"]
    assert culvert.value == pytest.approx(44.5)  # median of 40,42,44,45,48,50
    assert culvert.source == "fitted"            # computed, never "real"
    assert culvert.provenance.n == 6
    assert culvert.provenance.application_ref == "PWD/ALP/RTI/2026/123"
    assert culvert.previous["source"] == "assumed"

    eff = effective_register(reg, ov)
    assert eff["outage_mean_days_culvert"].default == pytest.approx(44.5)
    assert eff["outage_mean_days_culvert"].high == pytest.approx(44.5)  # widened, not clipped
    assert eff["outage_mean_days_culvert"].source == "fitted"
    # the original register is untouched
    assert reg["outage_mean_days_culvert"].default == 10.0


def test_small_sample_leaves_the_assumption_alone(tmp_path):
    folder = _write_reply(tmp_path / "reply")
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    assert "outage_mean_days_minor_bridge" not in ov.register
    skipped = {s["parameter"]: s for s in ov.skipped}
    assert skipped["outage_mean_days_minor_bridge"]["reason"] == "fewer_than_min_n"
    assert skipped["outage_mean_days_minor_bridge"]["n"] == 3
    assert MIN_SAMPLE == 5


def test_bad_dates_are_counted_not_imputed(tmp_path):
    folder = _write_reply(tmp_path / "reply")
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())
    cov = ov.coverage["closures"]
    assert cov["unparseable_closed_date"] == 1
    assert cov["negative_duration"] == 1


def test_repair_effect_comes_from_before_and_after_inspection(tmp_path):
    folder = _write_reply(tmp_path / "reply")
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    effect = ov.register["repair_effect_minor"]
    # five repairs recover 2 steps, one recovers 1 -> median 2
    assert effect.value == pytest.approx(2.0)
    assert effect.provenance.n == 6
    assert effect.source == "fitted"


def test_numeric_ratings_without_a_stated_scale_are_refused(tmp_path):
    folder = _write_reply(tmp_path / "reply", numeric_scale="unknown")
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    # the two S6 inspections are unusable, so the 1-step repair cannot be averaged in
    assert ov.coverage["inspections"]["refused_unstated_scale_or_unparseable"] == 2
    assert ov.register["repair_effect_minor"].provenance.n == 5
    assert ov.register["repair_effect_minor"].value == pytest.approx(2.0)


def _write_gap_reply(
    folder: Path, *, before: int, after: int, slope: int = 1, after_date: str = "2021-06-01"
) -> Path:
    """Six culverts with a pre-work inspection history, then a repair and one later inspection.

    Inspections sit at 2018/2019/2020-01-01 (before increments by ``slope`` each year), the
    minor repair completes 2020-06-01, and the only post-work inspection is ``after_date`` —
    a gap in which ordinary deterioration is expected.
    """
    folder = _write_reply(folder)
    ins = []
    for i in range(1, 7):
        for year, offset in ((2018, 0), (2019, slope), (2020, 2 * slope)):
            ins.append({"structure_id": f"S{i}", "inspection_date": f"{year}-01-01",
                        "rating": before - 2 * slope + offset, "rating_scheme": "1-4"})
        ins.append({"structure_id": f"S{i}", "inspection_date": after_date,
                    "rating": after, "rating_scheme": "1-4"})
    pd.DataFrame(ins).to_csv(folder / "inspections.csv", index=False)
    return folder


def test_a_repair_that_helped_is_not_a_contradiction_when_the_next_reading_is_worse(tmp_path):
    """Two years of ordinary deterioration must not read as a failed repair.

    History worsens one step a year (0 -> 1 -> 2 by the repair). Two and a half years after
    the January before the work the rating is 3: worse than the 2 measured before the work,
    but better than the 4.4 it would have reached with no repair at all, so the repair
    recovered about 1.4 steps.
    """
    # scheme ratings 3 -> 4 map to condition 2 -> 3, so the pre-work condition is 2 and
    # the cap (at 2) does not bind: this pair is about the counterfactual alone.
    folder = _write_gap_reply(tmp_path / "reply", before=3, after=4, after_date="2022-06-01")
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    cov = ov.coverage["repair_pairs"]
    assert cov["capped"] == 0
    assert cov["median_gap_years"] == pytest.approx(2.415, abs=0.01)
    # six minor repairs and six emergency restorations, every raw reading worse
    assert cov["by_intervention"] == {"minor": 6, "emergency": 6}
    assert cov["worsened_unadjusted"] == 12
    assert cov["worsened"] == 0
    assert cov["unadjudicated"] == 0         # a counterfactual exists, so each pair was judged
    assert cov["deterioration_steps_per_year"] == pytest.approx(1.0, abs=0.002)

    effect = ov.register["repair_effect_minor"]
    # counterfactual 2 + 1.0007 * 2.415 = 4.415, observed 3 -> 1.415 recovered
    assert effect.value == pytest.approx(1.415, abs=0.01)
    assert effect.provenance.n == 6


def test_a_worse_reading_without_history_is_unadjudicated_not_a_contradiction(tmp_path):
    """With one pre-work inspection there is no counterfactual, so no contradiction is claimed."""
    folder = _write_reply(tmp_path / "reply")
    ins = pd.read_csv(folder / "inspections.csv")
    ins.loc[ins["inspection_date"] == "2021-01-05", "rating"] = ["Severe"] * 5 + [4]
    ins.to_csv(folder / "inspections.csv", index=False)

    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    cov = ov.coverage["repair_pairs"]
    assert cov["deterioration_steps_per_year"] is None
    assert cov["worsened_unadjusted"] == 6
    assert cov["worsened"] == 0          # nothing to compare against: not a contradiction
    assert cov["unadjudicated"] == 6

    assert "repair_effect_minor" not in ov.register
    skipped = {s["parameter"]: s for s in ov.skipped}
    assert skipped["repair_effect_minor"]["reason"] == "fewer_than_min_n"
    assert skipped["repair_effect_minor"]["unadjudicated"] == 6
    assert skipped["repair_effect_minor"]["contradictions"] == 0


def test_post_repair_deterioration_is_added_back_not_counted_as_contradiction(tmp_path):
    """A worse first-after reading across a long gap is deterioration, not a contradiction."""
    # history 0 -> 1 -> 2 (one step per year), repair, then 3 a 1.42 years later.
    folder = _write_gap_reply(tmp_path / "reply", before=2, after=3)
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    cov = ov.coverage["repair_pairs"]
    assert cov["deterioration_steps_per_year"] == pytest.approx(1.0, abs=0.002)
    assert cov["worsened_unadjusted"] == 6      # raw before-minus-after is -1 everywhere
    assert cov["worsened"] == 0                 # after the adjustment, none contradict
    assert cov["median_gap_years"] == pytest.approx(1.415, abs=0.005)

    effect = ov.register["repair_effect_minor"]
    # -1 raw + 1 step/yr over the 1.42-year gap -> +0.42, not a discarded negative
    assert effect.value == pytest.approx(0.4155, abs=0.01)
    assert effect.provenance.n == 6
    assert "net of observed pre-work deterioration" in effect.provenance.detail
    # the note names the residual bias in both directions, not just the conservative one
    assert "understated" in effect.provenance.detail
    assert "overstated" in effect.provenance.detail


def test_one_contradiction_leaves_five_usable_pairs_and_the_override_applies(tmp_path):
    """A contradiction removes its pair, not the type: five usable pairs still override.

    Six culverts improve about 0.4 steps after a repair across a 1.4-year gap; one of them
    is re-inspected only half a year after the work, where the same deterioration rate
    cannot explain its drop, so that pair contradicts. Dropping it leaves five usable
    pairs, which is exactly ``MIN_SAMPLE``, so the median is fitted to those five.
    """
    folder = _write_gap_reply(tmp_path / "reply", before=2, after=3)
    ins = pd.read_csv(folder / "inspections.csv")
    # S6 gets its post-repair inspection after six months instead of 1.4 years: its raw
    # drop of one step is too large for 0.5 years of the observed 1.0 step/year trend.
    mask = (ins["structure_id"] == "S6") & (ins["inspection_date"] == "2021-06-01")
    ins.loc[mask, "inspection_date"] = "2020-12-01"
    ins.to_csv(folder / "inspections.csv", index=False)

    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    cov = ov.coverage["repair_pairs"]
    assert cov["worsened"] == 1
    effect = ov.register["repair_effect_minor"]
    assert effect.provenance.n == 5          # the contradictory pair is excluded
    assert effect.value == pytest.approx(0.416, abs=0.02)
    assert "repair_effect_minor" not in {s["parameter"] for s in ov.skipped}


def test_adjusted_recovery_is_capped_at_the_pre_work_condition(tmp_path):
    """A structure cannot recover more steps than it had: Good (0) is the floor.

    Each culvert is Fair (1) before the repair and Good (0) after it, but inspected 2.4
    years later. Adding that gap's deterioration would credit 3.4 recovered steps, more
    than the structure ever had, so the pair is capped at 1 and the cap is reported.
    """
    folder = _write_reply(tmp_path / "reply")
    ins = []
    for i in range(1, 7):
        # 1-4 scheme: 1 -> condition 0 (Good), 2 -> 1 (Fair)
        ins += [
            {"structure_id": f"S{i}", "inspection_date": "2019-01-01", "rating": 1,
             "rating_scheme": "1-4"},
            {"structure_id": f"S{i}", "inspection_date": "2020-01-01", "rating": 2,
             "rating_scheme": "1-4"},
            {"structure_id": f"S{i}", "inspection_date": "2022-06-01", "rating": 1,
             "rating_scheme": "1-4"},
        ]
    pd.DataFrame(ins).to_csv(folder / "inspections.csv", index=False)

    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    effect = ov.register["repair_effect_minor"]
    assert effect.value == pytest.approx(1.0)  # capped from ~3.4
    assert "capped at the pre-work condition" in effect.provenance.detail
    cov = ov.coverage["repair_pairs"]
    assert cov["capped"] == 12  # six minor repairs and six emergency restorations
    assert cov["cap_rule"] == "adjusted recovery capped at the pre-work condition"
    assert all(p["used"] == p["before"] for p in cov["capped_pairs"])
    assert cov["capped_pairs"][0]["adjusted_uncapped"] == pytest.approx(3.415, abs=0.02)


def test_a_genuine_contradiction_still_refuses_the_override(tmp_path):
    """With a flat pre-work history there is no deterioration to explain a worse rating."""
    folder = _write_gap_reply(tmp_path / "reply", before=1, after=4, slope=0)
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    cov = ov.coverage["repair_pairs"]
    assert cov["deterioration_steps_per_year"] == pytest.approx(0.0)
    assert cov["worsened"] == 6 == cov["worsened_unadjusted"]
    assert "repair_effect_minor" not in ov.register
    skipped = {s["parameter"]: s for s in ov.skipped}
    assert skipped["repair_effect_minor"]["reason"] == "insufficient_or_contradictory"
    assert skipped["repair_effect_minor"]["contradictions"] == 6


def test_without_pre_work_history_the_raw_change_is_used_and_flagged(tmp_path):
    folder = _write_reply(tmp_path / "reply")
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    cov = ov.coverage["repair_pairs"]
    assert cov["deterioration_steps_per_year"] is None
    assert cov["adjustment"] == (
        "no pre-work inspection interval; worse readings left unadjudicated"
    )
    detail = ov.register["repair_effect_minor"].provenance.detail
    assert "no pre-work history to adjust for deterioration" in detail
    assert "no way to correct it" in detail


def test_emergency_premium_and_unit_costs(tmp_path):
    folder = _write_reply(tmp_path / "reply")
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    assert ov.register["emergency_premium"].value == pytest.approx(1.75)
    assert ov.register["emergency_premium"].provenance.n == 6
    # base cost = median minor rate / COST_MULTIPLIER["minor"] = 1
    assert ov.rates["culvert"].value == pytest.approx(0.0205, abs=1e-6)
    assert ov.rates["culvert"].provenance.n == 6
    assert "COST_MULTIPLIER" in ov.rates["culvert"].provenance.detail


def _write_sor_crew_reply(folder: Path) -> Path:
    """A SoR with crew days: culvert/minor bridge quote minor *and* major items,
    major bridge quotes only major items (the case that used to be double-scaled)."""
    folder = _write_reply(folder)
    rows = []
    # culvert: 6 minor items (crew 4-7) + 2 major items (crew 12/14)
    for i, c in enumerate([4, 5, 5, 6, 6, 7]):
        rows.append({"item": f"cu minor {i}", "structure_type": "culvert",
                     "intervention": "minor", "rate_crore": 0.014 + 0.001 * i, "crew_days": c})
    for i, c in enumerate([12, 14]):
        rows.append({"item": f"cu major {i}", "structure_type": "culvert",
                     "intervention": "major", "rate_crore": 0.06 + 0.01 * i, "crew_days": c})
    # minor bridge: 6 minor items (crew 15-20) + 6 major items (crew 35-45)
    for i, c in enumerate([15, 16, 17, 18, 19, 20]):
        rows.append({"item": f"mb minor {i}", "structure_type": "minor bridge",
                     "intervention": "minor repair", "rate_crore": 0.050 + 0.003 * i, "crew_days": c})
    for i, c in enumerate([35, 38, 40, 42, 44, 45]):
        rows.append({"item": f"mb major {i}", "structure_type": "minor bridge",
                     "intervention": "major repair", "rate_crore": 0.22 + 0.01 * i, "crew_days": c})
    # major bridge: major items only (crew 60-80) -> base cost /4, crew days /2.5
    for i, c in enumerate([60, 64, 66, 72, 78, 80]):
        rows.append({"item": f"mbr major {i}", "structure_type": "major bridge",
                     "intervention": "major repair", "rate_crore": 0.30 + 0.02 * i, "crew_days": c})
    pd.DataFrame(rows).to_csv(folder / "sor.csv", index=False)
    return folder


def test_labour_days_are_scaled_back_from_the_intervention_that_set_the_base_cost(tmp_path):
    folder = _write_sor_crew_reply(tmp_path / "reply")
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    # culvert: minor rows only -> median 5.5, LABOUR_MULTIPLIER[minor] = 1
    assert ov.labour["culvert"].value == pytest.approx(5.5)
    # minor bridge: the 6 minor rows (median 17.5), never the 6 major rows (which would
    # have given 27.5 and then been multiplied by 2.5 for a major repair)
    assert ov.labour["minor_bridge"].value == pytest.approx(17.5)
    # major bridge: only major rows exist -> median 69 / LABOUR_MULTIPLIER[major] 2.5
    assert ov.labour["major_bridge"].value == pytest.approx(27.6)
    assert ov.labour["major_bridge"].provenance.n == 6
    assert "LABOUR_MULTIPLIER[major]=2.5" in ov.labour["major_bridge"].provenance.detail


def test_a_major_repair_costs_the_crew_days_the_reply_quotes(tmp_path):
    """The invariant the old code broke: crew days at the quoted intervention must round-trip."""
    from rra.app.register import apply_payload
    from rra.cost.interventions import Intervention

    folder = _write_sor_crew_reply(tmp_path / "reply")
    manifest, tables = load_reply(folder)
    reg = AssumptionRegister.default()
    ov = derive(manifest, tables, reg)
    written = write_outputs(ov, effective_register(reg, ov), tmp_path / "out")
    live = apply_payload(json.loads(Path(written["overrides"]).read_text(encoding="utf-8")))

    # the SoR's median major-repair crew days for a major bridge: 69
    assert live.sor.labour("major_bridge", Intervention.MAJOR) == pytest.approx(69.0)
    # a minor repair on a major bridge is the base figure, not a major item's crew days
    assert live.sor.labour("major_bridge", Intervention.MINOR) == pytest.approx(27.6)
    # a major repair on a minor bridge uses its minor rows scaled up: 17.5 * 2.5
    assert live.sor.labour("minor_bridge", Intervention.MAJOR) == pytest.approx(43.75)
    assert live.sor.labour("culvert", Intervention.MINOR) == pytest.approx(5.5)


def _write_rate_reply(folder: Path, culvert_minor: list[float], mb_minor: list[float], header: str) -> Path:
    """Replace the SoR with one under a chosen header, keeping every other table."""
    folder = _write_reply(folder)
    rows = [
        {"item": f"cu item {i}", "structure_type": "culvert", "intervention": "minor",
         header: rate}
        for i, rate in enumerate(culvert_minor)
    ] + [
        {"item": f"mb item {i}", "structure_type": "minor bridge", "intervention": "minor",
         header: rate}
        for i, rate in enumerate(mb_minor)
    ]
    pd.DataFrame(rows).to_csv(folder / "sor.csv", index=False)
    return folder


def test_lakh_rates_are_refused_instead_of_applied(tmp_path):
    """A bare 'Rate' header holding Rs lakh values must not 100x the schedule."""
    from rra.app.register import apply_payload

    # 0.018-0.023 cr and 0.050-0.065 cr, expressed as Rs lakh
    folder = _write_rate_reply(
        tmp_path / "reply",
        culvert_minor=[1.8, 1.9, 2.0, 2.1, 2.2, 2.3],
        mb_minor=[5.0, 5.2, 5.5, 5.8, 6.0, 6.5],
        header="Rate",
    )
    manifest, tables = load_reply(folder)
    reg = AssumptionRegister.default()
    ov = derive(manifest, tables, reg)

    assert ov.rates == {}, "no rate may be applied from an implausible scale"
    skipped = {s["parameter"]: s for s in ov.skipped}
    for stype in ("culvert", "minor_bridge"):
        record = skipped[f"base_cost::{stype}"]
        assert record["reason"] == "implausible_magnitude"
        assert record["n"] >= MIN_SAMPLE
        assert record["ratio_to_placeholder"] > MAX_COST_RATIO
        assert "Rs crore" in record["hint"]

    rejected = ov.coverage["schedule_of_rates"]["rejected_implausible"]
    assert {r["structure_type"] for r in rejected} == {"culvert", "minor_bridge"}
    assert ov.coverage["schedule_of_rates"]["max_cost_ratio"] == MAX_COST_RATIO

    # the placeholder schedule survives, so the plan is still fundable
    written = write_outputs(ov, effective_register(reg, ov), tmp_path / "out")
    live = apply_payload(json.loads(Path(written["overrides"]).read_text(encoding="utf-8")))
    assert live.sor.base_cost_crore["culvert"] == pytest.approx(0.02)
    assert live.sor.base_cost_crore["minor_bridge"] == pytest.approx(0.08)


def test_a_large_but_plausible_rate_is_still_accepted(tmp_path):
    """The guard must catch a unit error, not normal variation within the band."""
    folder = _write_rate_reply(
        tmp_path / "reply",
        culvert_minor=[0.20] * 6,       # 10x the placeholder: plausible, accepted
        mb_minor=[0.60] * 6,            # 7.5x the placeholder
        header="rate_crore",
    )
    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())

    assert ov.rates["culvert"].value == pytest.approx(0.20)
    assert ov.rates["minor_bridge"].value == pytest.approx(0.60)
    assert ov.coverage["schedule_of_rates"]["rejected_implausible"] == []


def test_outputs_carry_provenance_and_skips(tmp_path):
    folder = _write_reply(tmp_path / "reply")
    manifest, tables = load_reply(folder)
    reg = AssumptionRegister.default()
    ov = derive(manifest, tables, reg)
    eff = effective_register(reg, ov)

    out = tmp_path / "out"
    written = write_outputs(ov, eff, out, write_docs=True, root=tmp_path)
    payload = json.loads(Path(written["overrides"]).read_text(encoding="utf-8"))
    entry = payload["register"]["outage_mean_days_culvert"]
    assert entry["provenance"]["application_ref"] == "PWD/ALP/RTI/2026/123"
    assert entry["provenance"]["office"].startswith("EE PWD")
    assert payload["skipped"]
    assert Path(written["coverage"]).exists()

    docs = Path(written["docs"]).read_text(encoding="utf-8")
    assert "PWD/ALP/RTI/2026/123" in docs
    assert "`outage_mean_days_culvert`" in docs
    assert "Left as assumptions" in docs

    md = measured_markdown(ov, eff)
    assert "2026-11-20" in md


def test_unmapped_structure_and_work_types_are_reported(tmp_path):
    folder = _write_reply(tmp_path / "reply")
    df = pd.read_csv(folder / "structures.csv")
    df = pd.concat(
        [df, pd.DataFrame([{"structure_id": "C9", "structure_type": "causeway"}])],
        ignore_index=True,
    )
    df.to_csv(folder / "structures.csv", index=False)

    manifest, tables = load_reply(folder)
    ov = derive(manifest, tables, AssumptionRegister.default())
    assert "causeway" in ov.coverage["structures"]["unmapped_types"]
    assert ov.coverage["structures"]["mapped_type"] == 7
