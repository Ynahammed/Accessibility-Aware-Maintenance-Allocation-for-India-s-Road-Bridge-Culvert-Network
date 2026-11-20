"""Robustness analyses for the real-network allocation result.

E9/E11 compare maintenance policies on one district graph, one assumed register and one
set of eight monsoon scenarios, and the paper's headline is about the *baseline*: a
condition-first rule is not distinguishable from a random ordering of the same structures.
That claim has four obvious ways to be wrong, and each has a function here:

* **different spend.** The two rules buy different numbers of structures, so a per-crore
  ratio and an absolute loss can disagree in sign. :func:`spend_matched` repeats the
  comparison at a common planned budget.
* **absence of evidence.** An interval containing zero is not equivalence.
  :func:`precision_study` runs the comparison on a larger scenario sample, applies TOST at
  a declared margin, and reports the sample size the claim would actually need.
* **destination-conditioned selection.** The 30 assets were chosen on *hospital* solo loss
  before any school or islanding test. :func:`cap_sweep` and :func:`portfolio_variants`
  separate the asset set from the destination rule.
* **one baseline.** Condition-first is one rule, not the class of rules practice uses.
  :func:`heuristic_panel` adds age-, cost-, type- and road-class-first orderings.

Everything returns JSON-safe dictionaries so an experiment can persist them unchanged.
No function here writes files or mutates the district instance it is given.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from rra import pipeline
from rra.consequence.accessibility import AccessibilityModel
from rra.cost.interventions import Intervention, apply_effect
from rra.evaluate import stats
from rra.evaluate.equivalence import tost
from rra.fragility.fragility import failure_probability
from rra.network.alappuzha import DESTINATION_SETS, destination_access
from rra.optimize.instance import build_additive_instance
from rra.simulator import policies, step
from rra.simulator.optimized_policies import FixedPlanPolicy
from rra.optimize.multiperiod import solve_multiperiod


class Recorder:
    """Wrap a policy and keep the first year's plan (which assets, which intervention)."""

    def __init__(self, inner):
        self.inner = inner
        self.name = getattr(inner, "name", "policy")
        self.plan: dict | None = None

    def propose(self, assets, ctx):
        chosen = self.inner.propose(assets, ctx)
        if self.plan is None:
            self.plan = dict(chosen)
        return chosen


def run_policies(planners, world, scen, models, benefit) -> tuple[dict, dict]:
    """Run every policy on the same scenarios; return outcomes and year-1 plans."""
    outcomes: dict = {}
    plans: dict = {}
    for planner in planners:
        rec = Recorder(planner)
        outcomes[rec.name] = step.run(rec, world, scen, models, benefit=benefit)
        plans[rec.name] = {k: v.value for k, v in (rec.plan or {}).items()}
    return outcomes, plans


def policy_rows(outcomes, cfg) -> list:
    """The per-policy table every panel reports."""
    from rra.evaluate import metrics
    from rra.optimize.cvar import cvar

    rows = []
    for name, out in outcomes.items():
        pd = out.person_days
        rows.append(
            {
                "policy": name,
                "mean_person_days": float(pd.mean()),
                "mean_planned_crore": float(out.planned.mean()),
                "mean_emergency_crore": float(out.emergency.mean()),
                "mean_spend_crore": float(out.spend.mean()),
                "person_days_per_crore": metrics.access_lost_per_crore(
                    pd.sum(), out.spend.sum()
                ),
                "cvar_person_days": cvar(pd, cfg["cvar_alpha"]),
                "n_funded_year1": None,
            }
        )
    rows.sort(key=lambda r: r["person_days_per_crore"])
    return rows


def paired(outcomes, a, b, seed: int = 0) -> dict:
    """Paired bootstrap of ``a - b`` over the shared scenarios."""
    da, db = outcomes[a].person_days, outcomes[b].person_days
    ci = stats.paired_bootstrap_ci(da, db, rng=seed)
    return {
        "comparison": f"{a} - {b}",
        "mean_person_days": float(ci.mean),
        "ci_lo": float(ci.lo),
        "ci_hi": float(ci.hi),
        "n_scenarios": int(len(da)),
        "share_a_better": float(np.mean(da < db)),
        "share_b_better": float(np.mean(db < da)),
        "positive_means_a_worse": True,
    }


# --- 1. equal realised spend -------------------------------------------------------


def spend_matched(cfg, models, world, scen, benefit, budgets, planners) -> dict:
    """Repeat the panel at common *planned* budgets.

    Equal nominal budget is not equal spend: a rule that buys fewer, dearer structures
    leaves money on the table, and that is the whole reason the absolute and per-crore
    metrics disagree. Every policy here faces the same planned budget, so the remaining
    difference in realised spend is the rule's own utilisation, reported per row.

    The budget grid is chosen to bracket the condition-first rule's realised spend at the
    reporting budget, so one of the rows is the "same money" comparison the objection asks
    for. Emergency restoration is an outcome of failures, not a choice, so it is reported
    separately and never equalised.
    """
    rows = []
    comparisons = []
    for budget in budgets:
        scaled = replace(world, budget_crore=float(budget))
        outcomes, plans = run_policies(planners, scaled, scen, models, benefit)
        for name, out in outcomes.items():
            rows.append(
                {
                    "budget_crore_per_year": float(budget),
                    "planned_budget_total_crore": float(budget * cfg["years"]),
                    "policy": name,
                    "mean_person_days": float(out.person_days.mean()),
                    "mean_planned_crore": float(out.planned.mean()),
                    "mean_emergency_crore": float(out.emergency.mean()),
                    "mean_spend_crore": float(out.spend.mean()),
                    "n_funded_year1": len(plans[name]),
                }
            )
        for a, b in (("worst_first", "random"), ("additive_milp", "worst_first")):
            if a in outcomes and b in outcomes:
                comparisons.append(
                    dict(paired(outcomes, a, b, cfg["seed"]), budget_crore_per_year=float(budget))
                )

    # The point of the exercise: at which tested budget do the two rules actually spend
    # the same, and what does the paired difference look like there?
    matched = []
    for budget in budgets:
        at = {r["policy"]: r for r in rows if r["budget_crore_per_year"] == budget}
        if not {"worst_first", "random"} <= set(at):
            continue
        cmp_ = next(
            (c for c in comparisons
             if c["budget_crore_per_year"] == budget and c["comparison"] == "worst_first - random"),
            None,
        )
        wf, rnd = at["worst_first"], at["random"]
        matched.append(
            {
                "budget_crore_per_year": float(budget),
                "worst_first_planned_crore": wf["mean_planned_crore"],
                "random_planned_crore": rnd["mean_planned_crore"],
                "planned_spend_gap_crore": wf["mean_planned_crore"] - rnd["mean_planned_crore"],
                "paired": cmp_,
            }
        )
    return {
        "budgets_crore_per_year": [float(b) for b in budgets],
        "rows": rows,
        "comparisons": comparisons,
        "matched": matched,
        "note": (
            "Budgets are per simulated year; the two-year horizon makes the planned total "
            "twice the per-year figure. Emergency restoration is reported but not equalised: "
            "it is a consequence of failure, not an allocation choice."
        ),
    }


# --- 2. equivalence and precision --------------------------------------------------


def precision_study(
    cfg, models, world, benefit, planners, scenarios=(8, 40), margins=(0.05, 0.10)
) -> dict:
    """Practice-versus-chance at two scenario counts, with TOST and design arithmetic.

    The small sample reproduces the reporting panel exactly (same seed and draw order), so
    the larger run is an extension rather than a different experiment. The margin is a
    share of the additive policy's gain over condition-first at the same sample size: a
    difference smaller than 5-10% of what the optimiser recovers is not a difference the
    paper is claiming to detect.

    TOST is reported, not assumed: when both one-sided tests do not reject, the row is
    labelled inconclusive and the required sample size is what the reader should take away.
    """
    assets = list(world.assets)
    rows = []
    for n in scenarios:
        rng = np.random.default_rng(cfg["seed"] + 17)
        rain = np.exp(rng.normal(0.0, 0.4, size=(int(n), cfg["years"], len(assets))))
        scen = step.make_scenarios(assets, cfg["years"], int(n), rng, rain=rain)
        local = [p for p in planners if getattr(p, "name", "") in
                 {"worst_first", "random", "additive_milp"}]
        outcomes, _ = run_policies(local, world, scen, models, benefit)
        if not {"worst_first", "random", "additive_milp"} <= set(outcomes):
            continue
        gain = -float(
            outcomes["additive_milp"].person_days.mean()
            - outcomes["worst_first"].person_days.mean()
        )
        diff = outcomes["worst_first"].person_days - outcomes["random"].person_days
        base = {
            "n_scenarios": int(n),
            "additive_gain_vs_worst_first_person_days": gain,
            "worst_first_minus_random_person_days": float(diff.mean()),
            "sd_of_paired_difference": float(diff.std(ddof=1)) if diff.size > 1 else None,
            "share_scenarios_worst_first_better": float(np.mean(diff < 0)),
            "equivalence": [],
        }
        for share in margins:
            margin = max(abs(gain) * float(share), 1e-9)
            result = tost(diff, margin)
            base["equivalence"].append(
                dict(result.as_dict(), margin_share_of_additive_gain=float(share))
            )
        rows.append(base)
    return {
        "rows": rows,
        "note": (
            "The 8-scenario row reproduces the reporting panel. TOST rejects equivalence "
            "only when both one-sided tests reject; otherwise the reading is 'not "
            "distinguishable, and underpowered to claim equivalence at this margin'. "
            "required_n is the paired scenario count a TOST at that margin would need at "
            "80% power, so it is a design statement about this estimator."
        ),
    }


# --- 3. consequence-blind heuristic panel ------------------------------------------


def heuristic_panel(cfg, models, world, scen, benefit, road_class: dict) -> dict:
    """Condition-first against a *class* of rules that carry no consequence information.

    Age-first, cheapest-first, asset-type-first and road-class-first all use attributes an
    agency already holds; none of them looks at what a failure does to access. If the
    condition-first rule is indistinguishable from random, these should be too, and the
    Discussion can generalise from one baseline to the class.
    """
    planners = [
        policies.DoNothingPolicy(),
        policies.WorstFirstPolicy(),
        policies.RandomPolicy(),
        policies.age_first_policy(),
        policies.cheapest_first_policy(),
        policies.type_first_policy(),
        policies.road_class_first_policy(road_class),
    ]
    outcomes, plans = run_policies(planners, world, scen, models, benefit)
    rows = policy_rows(outcomes, cfg)
    for row in rows:
        row["n_funded_year1"] = len(plans.get(row["policy"], {}))
    blind = ["age_first", "cheapest_first", "type_first", "road_class_first", "worst_first"]
    comparisons = {}
    for name in blind:
        if name in outcomes:
            comparisons[f"{name}_vs_random"] = paired(outcomes, name, "random", cfg["seed"])
    return {
        "rows": rows,
        "comparisons": comparisons,
        "note": (
            "All rules buy the condition-appropriate intervention, so the comparison is "
            "about the ranking signal. Road-class priority is a declared ordering of OSM "
            "highway classes, not measured traffic: the district has no link counts."
        ),
    }


# --- 4. destination and cap sensitivity --------------------------------------------


def _gini(values) -> float:
    v = np.sort(np.asarray(values, dtype=float))
    n = v.size
    if n == 0 or v.sum() <= 0:
        return 0.0
    idx = np.arange(1, n + 1)
    return float((2 * (idx * v).sum()) / (n * v.sum()) - (n + 1) / n)


def benefit_split(cfg, models, assets, plan_options, solo_share) -> dict:
    """Attribute the plan's expected risk reduction to habitations (first order).

    Identical arithmetic to the reporting panel's equity block: the per-structure reduction
    in failure probability times outage days, split by that structure's measured solo-loss
    share. Kept in one function so the cap sweep and the headline panel cannot drift.
    """
    rain = np.exp(
        np.random.default_rng(cfg["seed"] + 4242).normal(0.0, 0.4, size=(64, 1))
    )
    benefit: dict = {}
    for a in assets:
        opt_value = plan_options.get(a.asset_id)
        if not opt_value or opt_value == Intervention.NONE.value:
            continue
        effect = models.effect(Intervention(opt_value))
        after = apply_effect(a.condition, effect)
        p_before = float(
            np.mean(
                [
                    failure_probability(int(a.condition), float(r[0]), models.fragility)
                    for r in rain
                ]
            )
        )
        p_after = (
            float(
                np.mean(
                    [
                        failure_probability(int(after), float(r[0]), models.fragility)
                        for r in rain
                    ]
                )
            )
            * effect.fragility_factor
        )
        weight = max(0.0, p_before - p_after) * models.outage(a)
        share = solo_share.get(a.asset_id) or {}
        total = sum(share.values())
        if weight <= 0 or total <= 0:
            continue
        for h, v in share.items():
            benefit[h] = benefit.get(h, 0.0) + weight * (v / total)
    return benefit


def equity_summary(benefit: dict, populations: dict) -> dict:
    total = sum(benefit.values())
    population = {h: float(p) for h, p in populations.items()}
    per_capita = sorted(
        (v / population[h] for h, v in benefit.items() if population.get(h, 0.0) > 0),
        reverse=True,
    )
    top = per_capita[: max(1, len(per_capita) // 100)]
    return {
        "note": (
            "Benefit is the plan's expected failure-probability reduction per funded "
            "structure, split across habitations by that structure's solo-loss share; a "
            "first-order attribution, not a re-solve of the joint network."
        ),
        "n_habitations_reached": len(benefit),
        "share_of_population_reached": float(
            sum(population[h] for h in benefit) / sum(population.values())
        )
        if population
        else 0.0,
        "gini_of_benefit_per_person": _gini(per_capita),
        "top_1pct_share_of_benefit": float(sum(top) / total) if total else 0.0,
    }


def cap_sweep(
    cfg, district, models, world, plans, register, caps, destinations=DESTINATION_SETS
) -> list:
    """Isolation and benefit split for every (destination, travel-time cap) cell.

    A hospital-only, 60-minute test is the most forgiving cell in the table: hospitals are
    the sparsest destination set and the cap is the loosest. Sweeping the cap as well as
    the destination separates the two causes instead of asserting which one matters.

    One Dijkstra pass per structure per cell serves the loss, the isolation count and the
    benefit share, which is what makes the sweep affordable on a 290k-node graph.
    """
    populations = {h: float(p) for h, p in district.habitations.items()}
    total_population = sum(populations.values())
    assets = list(world.assets.values())
    plan_options = plans.get("additive_milp", {})
    rows = []
    for destination in destinations:
        cap_default = float(register[f"travel_time_cap_{destination}"].default)
        weight = float(register[f"facility_weight_{destination}"].default)
        for cap in caps:
            cap = float(cap)
            if destination == "health" and abs(cap - cap_default) < 1e-9:
                acc = models.acc
            else:
                acc = destination_access(district, destination, cap, weight)
            times = acc.baseline_times(destination)
            reachable = [t for t in times.values() if np.isfinite(t)]
            within = sum(
                populations[h]
                for h, t in times.items()
                if populations.get(h, 0.0) > 0 and t < cap
            )
            solo_share = {}
            structures = []
            worst_extra = 0.0
            for a in assets:
                detail = acc.failure_detail(failed_nodes=[a.node], k=destination)
                solo_share[a.asset_id] = {h: d["loss"] for h, d in detail.items()}
                newly = [h for h, d in detail.items() if d["newly_isolated"]]
                extra = max((float(d.get("extra_minutes", 0.0)) for d in detail.values()),
                            default=0.0)
                worst_extra = max(worst_extra, extra)
                if newly:
                    structures.append(
                        {
                            "id": a.asset_id,
                            "isolated_habitations": len(newly),
                            "isolated_population": float(
                                sum(populations.get(h, 0.0) for h in newly)
                            ),
                        }
                    )
            benefit = benefit_split(cfg, models, assets, plan_options, solo_share)
            rows.append(
                {
                    "destination": destination,
                    "cap_minutes": cap,
                    "n_facilities": int(len(acc.facilities[destination])),
                    "baseline_median_minutes": float(np.median(reachable))
                    if reachable
                    else None,
                    "baseline_share_within_cap": within / total_population
                    if total_population
                    else 0.0,
                    "baseline_habitations_beyond_cap": int(
                        sum(1 for t in times.values() if not (t < cap))
                    ),
                    "n_single_points_of_failure": len(structures),
                    "single_points_of_failure": structures,
                    # summed over structures, so a habitation cut off by two structures
                    # counts twice; the count above is the structure count, which is the
                    # quantity the paper reports
                    "isolated_population_summed_over_structures": float(
                        sum(s["isolated_population"] for s in structures)
                    ),
                    "max_extra_one_way_minutes": float(worst_extra),
                    "equity": equity_summary(benefit, populations),
                    "plan_funded": len(plan_options),
                }
            )
    return rows


# --- 5. portfolio-selection sensitivity --------------------------------------------


def portfolio_variants(
    cfg, variants, register, live, cells=(("health", 60.0), ("school", 45.0))
):
    """Re-run the chance comparison and the islanding audit on alternative portfolios.

    ``variants`` is a list of ``(label, District, selection_note)``. Each is a portfolio of
    the same size built by a different ranking rule, so a difference in the islanding result
    is attributable to the selection rule rather than to the network or the destination set.
    The district is dropped from memory after use: each carries a 290k-node graph.
    """
    rows = []
    for label, district, note in variants:
        models = pipeline.build_models(
            district, register, seed=cfg["seed"], sor=live.sor
        )
        world = pipeline.build_world(district, register, seed=cfg["seed"])
        assets = list(world.assets.values())
        rng = np.random.default_rng(cfg["seed"] + 17)
        rain = np.exp(rng.normal(0.0, 0.4, size=(cfg["scenarios"], cfg["years"], len(assets))))
        scen = step.make_scenarios(
            [a.asset_id for a in assets], cfg["years"], cfg["scenarios"], rng, rain=rain
        )
        benefit = step.solo_benefit(world, models)
        planners = [
            policies.WorstFirstPolicy(),
            policies.RandomPolicy(),
            policies.BenefitCostPolicy(),
        ]
        outcomes, plans = run_policies(planners, world, scen, models, benefit)
        policy_row_list = policy_rows(outcomes, cfg)
        for row in policy_row_list:  # the funded count lives in the plan, not in the outcome
            row["n_funded_year1"] = len(plans.get(row["policy"], {}))
        entry = {
            "portfolio": label,
            "selection": note,
            "n_structures": len(assets),
            "structure_types": _type_counts(world),
            "policies": policy_row_list,
            "worst_first_vs_random": paired(outcomes, "worst_first", "random", cfg["seed"]),
            "destination_islanding": [],
        }
        for destination, cap in cells:
            acc = (
                models.acc
                if destination == "health"
                and abs(cap - models.acc.caps_min["health"]) < 1e-9
                else destination_access(
                    district, destination, cap,
                    float(register[f"facility_weight_{destination}"].default),
                )
            )
            counts = [
                acc.failure_detail(failed_nodes=[a.node], k=destination) for a in assets
            ]
            spof = sum(
                1 for detail in counts if any(d["newly_isolated"] for d in detail.values())
            )
            isolated_pop = sum(
                float(
                    sum(
                        district.habitations.get(h, 0.0)
                        for h, d in detail.items()
                        if d["newly_isolated"]
                    )
                )
                for detail in counts
            )
            entry["destination_islanding"].append(
                {
                    "destination": destination,
                    "cap_minutes": float(cap),
                    "n_single_points_of_failure": int(spof),
                    "isolated_population_total": float(isolated_pop),
                }
            )
        rows.append(entry)
        del models, world, district
    return {
        "variants": rows,
        "note": (
            "Portfolios are the same size and are placed on the same graph with the same "
            "assumed condition draw; only the ranking rule differs. Islanding is "
            "plan-independent, so it measures the selection rule directly."
        ),
    }


def _type_counts(world) -> dict:
    out: dict = {}
    for a in world.assets.values():
        out[a.structure_type] = out.get(a.structure_type, 0) + 1
    return out


# --- 6. cost of equity -------------------------------------------------------------

def equity_cost(
    cfg, models, world, solo_share, opt_rain, populations=None, exponents=(0.0, 0.5, 1.0, 1.5)
) -> dict:
    """What the plan gives up in total benefit to spread it more equally."""
    from rra.optimize.equity import equity_frontier

    assets = list(world.assets.values())
    inst = build_additive_instance(assets, models, opt_rain)
    frontier = equity_frontier(
        inst,
        solo_share,
        populations if populations is not None else models.acc.habitations,
        world.budget_crore,
        world.crew_days,
        exponents=exponents,
    )
    return frontier.as_dict()


# --- 7. two-period schedule --------------------------------------------------------

def multiperiod_replay(cfg, models, world, scen, benefit, opt_rain, myopic_outcome,
                       myopic_plan: dict) -> dict:
    """Compare a two-year schedule with the receding-horizon plan on the same scenarios."""
    assets = list(world.assets.values())
    plan = solve_multiperiod(
        assets, models, opt_rain, world.budget_crore, world.crew_days, solo=benefit
    )
    replay = FixedPlanPolicy({0: plan.year0, 1: plan.year1}, name="multiperiod_fixed")
    out = step.run(replay, world, scen, models, benefit=benefit)
    diff = out.person_days - myopic_outcome.person_days
    ci = stats.paired_bootstrap_ci(diff, np.zeros_like(diff), rng=cfg["seed"])
    return {
        "plan": plan.as_dict(),
        "mean_person_days": float(out.person_days.mean()),
        "mean_planned_crore": float(out.planned.mean()),
        "mean_emergency_crore": float(out.emergency.mean()),
        "myopic_mean_person_days": float(myopic_outcome.person_days.mean()),
        "paired_difference_vs_myopic": {
            "mean_person_days": float(ci.mean),
            "ci_lo": float(ci.lo),
            "ci_hi": float(ci.hi),
            "positive_means_schedule_worse": True,
        },
        "jaccard_year1_vs_myopic": _jaccard(set(plan.year0), set(myopic_plan)),
        "note": (
            "The receding-horizon additive policy re-solves each year at the state it "
            "reached, so it already adapts; what it lacks is lookahead and budget "
            "carryover. This comparison isolates those two additions. The schedule is "
            "solved on a deterministic expected-deterioration path, so it is a scheduling "
            "exercise, not an observed maintenance plan."
        ),
    }


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)
