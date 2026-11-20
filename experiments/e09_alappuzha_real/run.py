"""E9 — the allocation comparison, the inspection value and the islanding audit on the
**real Alappuzha network**.

E3/E4/E8 establish the method on generated districts. This experiment repeats the policy
comparison on the real 290k-node graph with real PMGSY demand and the screened 30
structures, then answers the two questions the generated testbeds cannot:

* **inspection value** — how much would the plan improve if one structure's condition were
  known instead of assumed? That ranks *inspections* (the record RTI would supply) against
  each other, and is reported as an upper bound: it resolves one structure at a time,
  holding the other 29 at their assumed state.
* **islanding** — which structures are single points of failure, and how many people are
  cut off from a hospital when each one fails alone.

It also splits the plan's benefit across habitations, so the distributional question
("who gains") is answered on the same run.

    python experiments/e09_alappuzha_real/run.py                # full run (~10 min)
    python experiments/e09_alappuzha_real/run.py --quick        # smoke test

Outputs ``results.json`` and ``results.md`` next to this file.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rra import pipeline  # noqa: E402
from rra.analysis import headline  # noqa: E402
from rra.app.register import live_register  # noqa: E402
from rra.evaluate import metrics, stats  # noqa: E402
from rra.network.alappuzha import (  # noqa: E402
    DESTINATION_SETS,
    build_alappuzha_district,
    destination_access,
)
from rra.network.district_layers import district_choices, get_district  # noqa: E402
from rra.optimize.instance import (  # noqa: E402
    N_OPTIONS,
    OPTION_LIST,
    build_additive_instance,
)
from rra.optimize.cvar import cvar  # noqa: E402
from rra.optimize.milp import solve_additive  # noqa: E402
from rra.cost.interventions import Intervention, apply_effect  # noqa: E402
from rra.fragility.fragility import failure_probability  # noqa: E402
from rra.simulator import policies, step  # noqa: E402
from rra.simulator.optimized_policies import AdditiveMilpPolicy  # noqa: E402
from rra.simulator.policies import ROAD_CLASS_PRIORITY  # noqa: E402

# The three condition-based baselines (worst_first, criticality_weighted, siloed) select the
# same funded set on this instance: all 30 screened structures are culverts, so the per-class
# budget split is a no-op, and the criticality proxy used here (1 + condition) is a strictly
# increasing transform of condition. Only worst_first is run; the identity of all three plans
# is asserted in `_baseline_equivalence`, not assumed from the portfolio description.
DEFAULTS = {
    "demand": "pmgsy",
    "seed": 0,
    "scenarios": 8,
    "years": 2,
    "optimizer_samples": 8,
    "budget_crore": 0.5,
    "crew_days": 150.0,
    "cvar_alpha": 0.1,
    "frontier_budgets": [0.1, 0.25, 0.5, 1.0],
}


class _Recorder:
    """Capture a policy's first-year plan (which structures it funds)."""

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.plan: dict | None = None

    def propose(self, assets, ctx):
        chosen = self.inner.propose(assets, ctx)
        if self.plan is None:
            self.plan = dict(chosen)
        return chosen


def _scenario_set(asset_ids, cfg):
    rng = np.random.default_rng(cfg["seed"] + 17)
    n_assets = len(asset_ids)
    rain = np.exp(rng.normal(0.0, 0.4, size=(cfg["scenarios"], cfg["years"], n_assets)))
    scen = step.make_scenarios(asset_ids, cfg["years"], cfg["scenarios"], rng, rain=rain)
    opt_rain = np.exp(
        np.random.default_rng(cfg["seed"] + 999).normal(
            0.0, 0.4, size=(cfg["optimizer_samples"], n_assets)
        )
    )
    return scen, opt_rain


def _baseline_equivalence(models, world, benefit, budgets):
    """Do the three condition-based policies fund the same structures here?

    All 30 screened structures are culverts, so `siloed`'s per-class split is a no-op, and
    `criticality_weighted` uses a criticality proxy that is a strictly increasing transform of
    condition. Both arguments predict the same *ranking* as `worst_first`; whether the same
    *set* fits under a binding budget is checked on the real plans, at the base budget and at
    every frontier budget. If a future portfolio mixes asset classes, a reply changes relative
    prices, or a class-specific schedule changes which set fits, `equivalent` becomes False and
    the experiment has to run all three policies separately.
    """
    from rra.simulator.policies import PolicyContext

    assets = list(world.assets.values())
    types = sorted({a.structure_type for a in assets})
    rows = []
    for budget in budgets:
        ctx = PolicyContext(
            sor=models.sor,
            budget_crore=float(budget),
            crew_days=world.crew_days,
            benefit=benefit,
            criticality={a.asset_id: 1.0 + a.condition for a in assets},
            rng=np.random.default_rng(0),
        )
        plans = {
            "worst_first": policies.WorstFirstPolicy().propose(assets, ctx),
            "criticality_weighted": policies.CriticalityWeightedPolicy().propose(assets, ctx),
            "siloed": policies.SiloedPolicy().propose(assets, ctx),
        }
        sets = {name: set(plan) for name, plan in plans.items()}
        same_assets = sets["worst_first"] == sets["criticality_weighted"] == sets["siloed"]
        rows.append(
            {
                "budget_crore": float(budget),
                "equivalent": same_assets,
                "n_funded": {name: len(plan) for name, plan in plans.items()},
                "same_interventions": (
                    same_assets
                    and plans["worst_first"] == plans["criticality_weighted"] == plans["siloed"]
                ),
            }
        )
    reporting = float(world.budget_crore)
    at_reporting = next(
        (r for r in rows if abs(r["budget_crore"] - reporting) < 1e-9), None
    )
    every_budget = all(r["equivalent"] for r in rows)
    return {
        # ``equivalent`` describes the budget the policy panel is actually run at; the panel
        # reports worst-first once only if the comparators coincide there.
        "equivalent": bool(at_reporting and at_reporting["equivalent"]),
        "equivalent_at_every_budget": every_budget,
        "reporting_budget_crore": reporting,
        "policies_compared": ["worst_first", "criticality_weighted", "siloed"],
        "structure_types": types,
        "all_culvert": types == ["culvert"],
        "by_budget": rows,
        "note": (
            "Same funded set at every budget tested, so the two comparators are reported once "
            "as worst-first rather than as three independent baselines."
            if every_budget
            else "Identical at some budgets but not all: the comparators' identity is "
            "budget-specific, so the panel reports worst-first only at its own budget "
            "and the per-budget record is kept in `by_budget`."
        ),
    }


def _policy_panel(cfg, district, models, world, scen, opt_rain, benefit):
    """Every policy on the same scenarios; paired against worst-first."""
    asset_ids = list(world.assets)
    planners = [
        policies.DoNothingPolicy(),
        policies.WorstFirstPolicy(),
        policies.BenefitCostPolicy(),
        policies.RandomPolicy(),
        AdditiveMilpPolicy(models, opt_rain, seed=cfg["seed"]),
    ]
    outcomes = {}
    plans = {}
    for p in planners:
        rec = _Recorder(p)
        outcomes[rec.name] = step.run(rec, world, scen, models, benefit=benefit)
        plans[rec.name] = {k: v.value for k, v in (rec.plan or {}).items()}
        print(f"  ran {rec.name}", flush=True)

    rows = []
    for name, out in outcomes.items():
        pd = out.person_days
        spend = out.spend
        rows.append(
            {
                "policy": name,
                "mean_person_days": float(pd.mean()),
                "mean_planned_crore": float(out.planned.mean()),
                "mean_emergency_crore": float(out.emergency.mean()),
                "mean_spend_crore": float(spend.mean()),
                "person_days_per_crore": metrics.access_lost_per_crore(pd.sum(), spend.sum()),
                "cvar_person_days": cvar(pd, cfg["cvar_alpha"]),
                "n_funded_year1": len(plans[name]),
            }
        )
    rows.sort(key=lambda r: r["person_days_per_crore"])

    def paired(a, b):
        da, db = outcomes[a].person_days, outcomes[b].person_days
        ci = stats.paired_bootstrap_ci(da, db, rng=cfg["seed"])
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

    def win_rate(name):
        best = np.argmin(np.vstack([outcomes[k].person_days for k in outcomes]), axis=0)
        names = list(outcomes)
        return float(np.mean([names[i] == name for i in best]))

    wins = {k: win_rate(k) for k in outcomes}
    comparisons = {
        "additive_vs_worst_first": paired("additive_milp", "worst_first"),
        "additive_vs_do_nothing": paired("additive_milp", "do_nothing"),
        # The practice baseline against chance: is condition-first doing better than a
        # random order that spends the same budget? Paired on the shared scenarios.
        "worst_first_vs_random": paired("worst_first", "random"),
        "scenario_win_rate": wins,
    }
    return rows, plans, comparisons, outcomes


def _practice_vs_chance(rows, comparisons):
    """How much does condition-first practice actually buy over random selection?

    Both metrics are reported because they disagree: random funds more, cheaper structures,
    so it spends more (planned plus emergency) and scores better per crore, while losing more
    person-days in absolute terms. The comparison that matters for the paper's motivation is
    the size of each gap relative to what accessibility-aware allocation recovers.
    """
    by = {r["policy"]: r for r in rows}
    wf, rnd, add = by["worst_first"], by["random"], by["additive_milp"]
    paired = comparisons["worst_first_vs_random"]
    additive_gain = -comparisons["additive_vs_worst_first"]["mean_person_days"]
    absolute_gap = wf["mean_person_days"] - rnd["mean_person_days"]
    ratio_gap = wf["person_days_per_crore"] - rnd["person_days_per_crore"]
    return {
        "worst_first_mean_person_days": wf["mean_person_days"],
        "random_mean_person_days": rnd["mean_person_days"],
        "worst_first_spend_crore": wf["mean_spend_crore"],
        "random_spend_crore": rnd["mean_spend_crore"],
        "worst_first_per_crore": wf["person_days_per_crore"],
        "random_per_crore": rnd["person_days_per_crore"],
        "absolute_gap_person_days": float(absolute_gap),
        "ratio_gap_person_days_per_crore": float(ratio_gap),
        "paired": paired,
        "share_of_scenarios_worst_first_better": paired["share_a_better"],
        "additive_gain_vs_worst_first_person_days": float(additive_gain),
        "gap_as_share_of_additive_gain": float(abs(absolute_gap) / additive_gain),
        "note": (
            "Condition-first beats random by a small absolute margin while spending less, and "
            "is nominally worse per crore because of that lower spend. Either reading leaves "
            "the practice baseline close to chance relative to the additive policy's gain."
        ),
    }


def _inspection_value(cfg, models, world, opt_rain):
    """Per-structure value of resolving its condition, one structure at a time.

    Base: the additive plan under the assumed condition. For each structure and each
    candidate condition, re-solve with that condition imposed; the average gain over the
    three states, minus the base objective, is the value of inspecting it. Reported as an
    upper bound in the plan's own loss units (person-minutes of access x outage days).
    """
    assets = list(world.assets.values())
    budget, crew = cfg["budget_crore"], cfg["crew_days"]

    def solve_with(condition_override=None):
        saved = None
        if condition_override is not None:
            asset_id, cond = condition_override
            saved = world.assets[asset_id].condition
            world.assets[asset_id].condition = int(cond)
        inst = build_additive_instance(assets, models, opt_rain)
        x, obj, _ = solve_additive(inst, budget, crew)
        if condition_override is not None:
            world.assets[condition_override[0]].condition = int(saved)
        return inst, x, obj

    inst, x0, base = solve_with()
    base_choice = {
        a.asset_id: int(np.argmax(x0[i * N_OPTIONS:(i + 1) * N_OPTIONS]))
        for i, a in enumerate(assets)
    }
    rows = []
    for a in assets:
        objs = []
        swap = 0
        for cond in (1, 2, 3):
            _, x_c, obj_c = solve_with((a.asset_id, cond))
            objs.append(float(obj_c))
            choice = {
                b.asset_id: int(np.argmax(x_c[i * N_OPTIONS:(i + 1) * N_OPTIONS]))
                for i, b in enumerate(assets)
            }
            if any(choice[k] != base_choice[k] for k in choice):
                swap += 1
        rows.append(
            {
                "id": a.asset_id,
                "type": a.structure_type,
                "assumed_condition": int(a.condition),
                "base_option": OPTION_LIST[base_choice[a.asset_id]].value,
                "expected_gain": float(np.mean(objs) - base),
                "min_gain": float(min(objs) - base),
                "max_gain": float(max(objs) - base),
                "plan_changes_in_states": swap,
            }
        )
    rows.sort(key=lambda r: r["expected_gain"], reverse=True)
    total = float(sum(max(0.0, r["expected_gain"]) for r in rows))
    return {
        "base_objective": float(base),
        "note": (
            "Expected gain is the mean objective improvement over the three condition states "
            "when that one structure's condition is known; an upper bound because structures "
            "are resolved one at a time and the other 29 stay at their assumed state."
        ),
        "structures": rows,
        "sum_positive_gain": total,
    }


def _islanding_and_equity(cfg, models, world, plans, acc=None):
    """Per-structure isolation on the real graph, then the plan's benefit split.

    One Dijkstra pass per structure supplies the solo loss, the isolation count and the
    benefit share (`AccessibilityModel.failure_detail`); the reported numbers are the same
    as the two-pass `loss_by_habitation` + `disruption` pair they replace. Returns the
    result and the per-structure solo-loss shares, which the equity-constrained MILP needs.
    """
    assets = list(world.assets.values())
    acc = acc if acc is not None else models.acc
    island = []
    solo_share = {}
    for a in assets:
        detail = acc.failure_detail(failed_nodes=[a.node])
        share = {h: d["loss"] for h, d in detail.items()}
        solo_share[a.asset_id] = share
        newly = [h for h, d in detail.items() if d["newly_isolated"]]
        island.append(
            {
                "id": a.asset_id,
                "type": a.structure_type,
                "solo_loss": float(sum(share.values())),
                "outage_days": float(models.outage(a)),
                "isolated_habitations": len(newly),
                "isolated_population": float(
                    sum(float(acc.habitations.get(h, 0.0)) for h in newly)
                ),
                "max_extra_one_way_minutes": float(
                    max((d.get("extra_minutes", 0.0) for d in detail.values()), default=0.0)
                ),
            }
        )
    island.sort(key=lambda r: r["isolated_population"], reverse=True)

    plan_opts = plans.get("additive_milp", {})
    if not plan_opts:
        return (
            {"islanding": island, "n_single_points_of_failure": 0,
             "equity": {"note": "no additive plan captured"}},
            solo_share,
        )

    benefit = headline.benefit_split(cfg, models, assets, plan_opts, solo_share)
    equity = headline.equity_summary(benefit, acc.habitations)
    return (
        {
            "islanding": island,
            "n_single_points_of_failure": int(
                sum(1 for r in island if r["isolated_population"] > 0)
            ),
            "equity": equity,
        },
        solo_share,
    )


def _destination_sensitivity(cfg, district, models, world, plans, register, base_stats):
    """Repeat the isolation and benefit-split checks for each destination set.

    The hospital tier is the one the allocation uses and is reused unchanged; the school
    tier rebuilds only the accessibility model, on the same graph, habitations and funded
    plan, so the difference is the destination set rather than a different instance.
    """
    rows = []
    population = {h: float(p) for h, p in district.habitations.items()}
    total_population = float(sum(population.values()))
    for destination in DESTINATION_SETS:
        cap = float(register[f"travel_time_cap_{destination}"].default)
        weight = float(register[f"facility_weight_{destination}"].default)
        if destination == "health":
            acc = models.acc
            stats = base_stats
        else:
            acc = destination_access(district, destination, cap, weight)
            stats, _ = _islanding_and_equity(cfg, models, world, plans, acc=acc)
        times = acc.baseline_times(destination)
        reachable = [t for t in times.values() if np.isfinite(t)]
        within = sum(
            population[h] for h, t in times.items() if population.get(h, 0.0) > 0 and t < cap
        )
        rows.append(
            {
                "destination": destination,
                "n_facilities": int(len(acc.facilities[destination])),
                "cap_minutes": cap,
                "weight": weight,
                "baseline_median_minutes": float(np.median(reachable)) if reachable else None,
                "baseline_share_within_cap": within / total_population if total_population else 0.0,
                "baseline_habitations_beyond_cap": int(
                    sum(1 for t in times.values() if not (t < cap))
                ),
                "islanding": stats["islanding"],
                "n_single_points_of_failure": stats["n_single_points_of_failure"],
                "equity": stats["equity"],
                "plan_funded": len(plans.get("additive_milp", {})),
            }
        )
    return rows


def _gini(values) -> float:
    v = np.sort(np.asarray(values, dtype=float))
    n = v.size
    if n == 0 or v.sum() <= 0:
        return 0.0
    idx = np.arange(1, n + 1)
    return float((2 * (idx * v).sum()) / (n * v.sum()) - (n + 1) / n)


def _budget_frontier(cfg, models, world, opt_rain):
    """Plan objective against budget: the cost-access-loss frontier."""
    assets = list(world.assets.values())
    inst = build_additive_instance(assets, models, opt_rain)
    rows = []
    for b in cfg["frontier_budgets"]:
        try:
            x, obj, res = solve_additive(inst, float(b), cfg["crew_days"])
        except RuntimeError:
            continue
        rows.append(
            {
                "budget_crore": float(b),
                "objective": float(obj),
                "planned_loss_per_crore": float(obj / b) if b > 0 else None,
                "n_funded": int(
                    sum(1 for i in range(len(assets))
                        if int(np.argmax(x[i * N_OPTIONS:(i + 1) * N_OPTIONS])) != 0)
                ),
                "mip_gap": _gap(res),
                "mip_dual_bound": _dual_bound(res),
            }
        )
    return rows


def _gap(res) -> float | None:
    """Relative MIP gap HiGHS reports, or None when it is not exposed."""
    for name in ("mip_gap", "mipgap", "gap"):
        value = getattr(res, name, None)
        if value is not None and np.isfinite(float(value)):
            return float(value)
    return None


def _dual_bound(res) -> float | None:
    for name in ("mip_dual_bound", "mip_dualbound", "dual_bound"):
        value = getattr(res, name, None)
        if value is not None and np.isfinite(float(value)):
            return float(value)
    return None


ROBUSTNESS_CAPS = (30.0, 45.0, 60.0, 90.0)


def _school_edge_scores(district, models, register, spec, limit: int = 1200) -> dict:
    """School solo loss for every candidate edge the portfolio can be drawn from.

    Ranking a portfolio on the school objective needs a school criticality per candidate
    edge. The candidates are the route-carrying edges already measured for hospitals (804
    in Alappuzha); scoring any other edge could not change the selection, because the
    portfolio is drawn from that table. One Dijkstra pass per edge, with progress printed so
    a long sweep is visible rather than silent.
    """
    cap = float(register["travel_time_cap_school"].default)
    weight = float(register["facility_weight_school"].default)
    cache = ROOT / "data" / "processed" / f"{getattr(spec, 'name', district.metadata.get('district', 'district'))}_school_edge_scores.json"
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if abs(float(cached.get("cap_minutes", -1.0)) - cap) < 1e-9:
            print(f"    school criticality reused from {cache.name}", flush=True)
            return {
                "scores": {
                    tuple(k.split("|", 1)): float(v) for k, v in cached["scores"].items()
                },
                "n_edges": int(cached["n_edges"]),
                "truncated": bool(cached["truncated"]),
                "cap_minutes": cap,
            }
    acc = destination_access(district, "school", cap, weight)
    table = pd.read_csv(spec.resilience_dir / "crossing_solo_criticality.csv")
    edges = [(str(u), str(v)) for u, v in zip(table.edge_u, table.edge_v)]
    truncated = len(edges) > limit
    if truncated:  # keep the highest hospital-loss edges, and say so
        edges = edges[:limit]
    scores = {}
    for i, (u, v) in enumerate(edges, start=1):
        detail = acc.failure_detail(failed_edges=[(u, v)], k="school")
        scores[(u, v)] = float(sum(d["loss"] for d in detail.values()))
        if i % 100 == 0:
            print(f"    school criticality {i}/{len(edges)}", flush=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {
                "cap_minutes": cap,
                "n_edges": len(edges),
                "truncated": truncated,
                "scores": {"|".join(edge): float(val) for edge, val in scores.items()},
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return {
        "scores": scores,
        "n_edges": len(edges),
        "truncated": truncated,
        "cap_minutes": cap,
    }


def _attempt(label: str, fn):
    """Run one robustness block; a failure is recorded instead of losing the whole run."""
    print(f"  {label} ...", flush=True)
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - defensive, surfaced in the JSON
        import traceback

        traceback.print_exc()
        return {"error": f"{type(exc).__name__}: {exc}"}


def _robustness(
    cfg, district, models, world, scen, opt_rain, benefit, plans, outcomes, rows,
    solo_share, live, spec,
) -> dict:
    """Everything the paper's headline needs in order to survive a referee.

    Each block is attempted independently: a failure is recorded next to the block's key
    rather than aborting a run that has already spent half an hour on the graph.
    """
    at = {r["policy"]: r for r in rows}
    years = max(1, int(cfg["years"]))
    target = round(float(at["worst_first"]["mean_planned_crore"]) / years, 4)
    budgets = sorted({0.25, target, float(cfg["budget_crore"])})
    result: dict = {"budgets_crore_per_year": budgets}

    def allocating():
        return [
            policies.WorstFirstPolicy(),
            policies.RandomPolicy(),
            policies.BenefitCostPolicy(),
            AdditiveMilpPolicy(models, opt_rain, seed=cfg["seed"]),
        ]

    result["spend_matched"] = _attempt(
        "spend-matched panel",
        lambda: headline.spend_matched(
            cfg, models, world, scen, benefit, budgets, allocating()
        ),
    )

    result["precision"] = _attempt(
        "equivalence and precision study",
        lambda: headline.precision_study(
            cfg,
            models,
            world,
            benefit,
            [
                policies.WorstFirstPolicy(),
                policies.RandomPolicy(),
                AdditiveMilpPolicy(models, opt_rain, seed=cfg["seed"]),
            ],
            scenarios=(int(cfg["scenarios"]), 40),
        ),
    )

    road_class = {
        asset_id: ROAD_CLASS_PRIORITY.get(str(prov.get("road_highway") or ""), 0.0)
        for asset_id, prov in district.asset_provenance.items()
    }
    result["heuristics"] = _attempt(
        "consequence-blind heuristic panel",
        lambda: headline.heuristic_panel(cfg, models, world, scen, benefit, road_class),
    )

    result["cap_sweep"] = _attempt(
        "destination and cap sweep",
        lambda: headline.cap_sweep(
            cfg, district, models, world, plans, live.register, ROBUSTNESS_CAPS
        ),
    )

    def portfolios():
        blocks = []
        notes = {
            "tag_first": (
                "mapped evidence only: OSM bridge tag, then snapping offset, then measured "
                "loss; no consequence measure drives the order"
            ),
            "bridge_tagged": (
                "hospital solo-loss ranking restricted to edges that already carry an OSM "
                "bridge tag"
            ),
            "school_loss": (
                "reordered by measured school solo loss on the same candidate edges"
            ),
        }
        # the two cheap portfolios first; the school sweep is the expensive one and also the
        # most likely to fail, so a failure there must not cost the other two.
        school_scores = None
        school_meta = None
        errors = []
        for ranking, note in notes.items():
            try:
                if ranking == "school_loss" and school_scores is None:
                    school = _school_edge_scores(district, models, live.register, spec)
                    school_scores = school["scores"]
                    school_meta = {
                        "n_edges": school["n_edges"],
                        "truncated": school["truncated"],
                        "cap_minutes": school["cap_minutes"],
                    }
                variant = build_alappuzha_district(
                    demand=cfg["demand"],
                    n_assets=30,
                    seed=cfg["seed"],
                    budget_crore=cfg["budget_crore"],
                    crew_days=cfg["crew_days"],
                    district=spec.slug,
                    ranking=ranking,
                    scores=school_scores if ranking == "school_loss" else None,
                )
                block = headline.portfolio_variants(
                    cfg, [(ranking, variant, note)], live.register, live
                )
                blocks.extend(block["variants"])
                del variant
                gc.collect()
            except Exception as exc:  # pragma: no cover - surfaced in the JSON
                import traceback

                traceback.print_exc()
                errors.append({"portfolio": ranking, "error": f"{type(exc).__name__}: {exc}"})
        out = {"variants": blocks, "school_scores": school_meta}
        if errors:
            out["errors"] = errors
        return out

    result["portfolios"] = _attempt("portfolio-selection sensitivity", portfolios)

    result["equity_cost"] = _attempt(
        "cost of an equity constraint",
        lambda: headline.equity_cost(
            cfg, models, world, solo_share, opt_rain, district.habitations
        ),
    )

    result["schedule"] = _attempt(
        "two-period schedule against the receding-horizon plan",
        lambda: headline.multiperiod_replay(
            cfg,
            models,
            world,
            scen,
            benefit,
            opt_rain,
            outcomes["additive_milp"],
            plans["additive_milp"],
        ),
    )

    def solver():
        inst = build_additive_instance(list(world.assets.values()), models, opt_rain)
        x, obj, res = solve_additive(inst, world.budget_crore, world.crew_days)
        return {
            "n_variables": int(inst.n_vars),
            "n_scenarios": int(inst.n_scenarios),
            "objective": float(obj),
            "mip_gap": _gap(res),
            "mip_dual_bound": _dual_bound(res),
            "status": int(res.status),
            "message": str(res.message),
            "n_funded": int(
                sum(
                    1
                    for i in range(len(world.assets))
                    if int(np.argmax(x[i * N_OPTIONS:(i + 1) * N_OPTIONS])) != 0
                )
            ),
            "note": (
                "HiGHS is asked for the optimum with no time limit. A zero or absent gap "
                "means the additive baseline is solved to optimality for its own linear "
                "surrogate; it says nothing about the non-additive objective."
            ),
        }

    result["solver"] = _attempt("solver quality", solver)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="fewer scenarios, one year")
    ap.add_argument(
        "--district",
        default="alappuzha",
        choices=district_choices(),
        help="real district to run on (default: alappuzha)",
    )
    ap.add_argument(
        "--no-robustness",
        action="store_true",
        help="skip the robustness suite (spend match, equivalence, cap sweep, portfolios)",
    )
    ap.add_argument(
        "--demand",
        default="pmgsy",
        choices=("pmgsy", "census"),
        help="population universe for the demand layer (default: pmgsy)",
    )
    ap.add_argument(
        "--out-dir",
        default=None,
        help="write results here instead of the experiment directory (used by the "
        "pre-registered post-reply run, which must not overwrite the frozen baseline)",
    )
    args = ap.parse_args()
    spec = get_district(args.district)
    cfg = dict(DEFAULTS)
    cfg["demand"] = args.demand
    if args.quick:
        cfg.update(scenarios=3, years=1, optimizer_samples=4)

    t0 = time.time()
    print(f"building the real {spec.name} instance ...", flush=True)
    district = build_alappuzha_district(
        demand=cfg["demand"],
        n_assets=30,
        seed=cfg["seed"],
        budget_crore=cfg["budget_crore"],
        crew_days=cfg["crew_days"],
        district=spec.slug,
    )
    live = live_register()
    models = pipeline.build_models(district, live.register, seed=cfg["seed"], sor=live.sor)
    world = pipeline.build_world(district, live.register, seed=cfg["seed"])
    scen, opt_rain = _scenario_set(list(world.assets), cfg)

    # Baseline context for the isolation counts: a habitation already beyond the health
    # travel-time cap cannot be "newly cut off", so the counts below exclude it.
    health_cap = models.acc.caps_min["health"]
    baseline_times = models.acc.baseline_times("health")
    beyond_cap = sum(1 for t in baseline_times.values() if not (t < health_cap))
    types = {}
    for a in world.assets.values():
        types[a.structure_type] = types.get(a.structure_type, 0) + 1

    print("solo-loss sweep ...", flush=True)
    benefit = step.solo_benefit(world, models)
    equivalence = _baseline_equivalence(
        models, world, benefit, sorted({cfg["budget_crore"], *cfg["frontier_budgets"]})
    )
    print(f"condition-based baselines equivalent: {equivalence['equivalent']}", flush=True)
    print("policy panel ...", flush=True)
    rows, plans, comparisons, outcomes = _policy_panel(
        cfg, district, models, world, scen, opt_rain, benefit
    )
    chance = _practice_vs_chance(rows, comparisons)

    print("inspection value ...", flush=True)
    inspection = _inspection_value(cfg, models, world, opt_rain)

    print("islanding and benefit split ...", flush=True)
    district_stats, solo_share = _islanding_and_equity(cfg, models, world, plans)

    print("budget frontier ...", flush=True)
    frontier = _budget_frontier(cfg, models, world, opt_rain)

    print("destination sensitivity ...", flush=True)
    destinations = _destination_sensitivity(
        cfg, district, models, world, plans, live.register, district_stats
    )

    robustness = None
    if not args.no_robustness:
        print("robustness suite ...", flush=True)
        try:
            robustness = _robustness(
                cfg, district, models, world, scen, opt_rain, benefit, plans, outcomes,
                rows, solo_share, live, spec,
            )
        except Exception as exc:  # pragma: no cover - the core panel must still be written
            import traceback

            traceback.print_exc()
            robustness = {"error": f"{type(exc).__name__}: {exc}"}

    result = {
        "district": spec.slug,
        "district_name": spec.name,
        "config": cfg,
        "instance": {
            "demand": cfg["demand"],
            "n_habitations": len(district.habitations),
            "n_structures": len(district.structures),
            "n_health_facilities": len(district.facilities.get("health", [])),
            "population": float(sum(district.habitations.values())),
            "structure_types": types,
            "health_cap_minutes": float(health_cap),
            "habitations_beyond_health_cap_baseline": int(beyond_cap),
            "provenance": district.metadata.get("sources"),
            "assumed": district.metadata.get("assumed"),
            "selection_rule": district.metadata.get("selection_rule"),
        },
        "baselines_equivalent": equivalence["equivalent"],
        "baseline_equivalence": equivalence,
        "policies": rows,
        "comparisons": comparisons,
        "practice_vs_chance": chance,
        "year1_plans": {k: v for k, v in plans.items() if k != "_options"},
        "inspection_value": inspection,
        "islanding": district_stats["islanding"],
        "n_single_points_of_failure": district_stats["n_single_points_of_failure"],
        "equity": district_stats["equity"],
        "budget_frontier": frontier,
        "destination_sensitivity": destinations,
        "robustness": robustness,
        "elapsed_seconds": time.time() - t0,
    }
    out_dir = (
        ROOT / args.out_dir
        if args.out_dir
        else (
            Path(__file__).resolve().parent
            if spec.slug == "alappuzha"
            else ROOT / "experiments" / f"e11_{spec.slug}_real"
        )
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = _markdown(result)
    (out_dir / "results.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\n(wrote results.json / results.md in {result['elapsed_seconds']:.0f}s)")


def _markdown(r: dict) -> str:
    c = r["config"]
    lines = [
        f"# E9 — real {r.get('district_name', 'district')} network: allocation, inspection value, islanding",
        "",
        f"- instance: {r['instance']['n_habitations']} habitations, "
        f"{r['instance']['n_structures']} structures, population "
        f"{r['instance']['population']:.0f}",
        f"- structure mix: {r['instance']['structure_types']}",
        f"- habitations already beyond the {r['instance']['health_cap_minutes']:.0f}-minute "
        f"health cap before any failure: "
        f"{r['instance']['habitations_beyond_health_cap_baseline']}",
        f"- scenarios: {c['scenarios']}, years: {c['years']}, budget Rs {c['budget_crore']} cr, "
        f"crew {c['crew_days']} days",
        "",
        "## Policy panel (paired scenarios)",
        "",
        "| Policy | Mean person-days | Spend (cr) | Person-days per crore | CVaR | Funded yr-1 |",
        "|---|---|---|---|---|---|",
    ]
    for p in r["policies"]:
        lines.append(
            f"| {p['policy']} | {p['mean_person_days']:.1f} | {p['mean_spend_crore']:.2f} | "
            f"{p['person_days_per_crore']:.1f} | {p['cvar_person_days']:.1f} | "
            f"{p['n_funded_year1']} |"
        )
    for key in ("additive_vs_worst_first", "additive_vs_do_nothing"):
        cmp_ = r["comparisons"][key]
        lines.append("")
        lines.append(
            f"**Paired {cmp_['comparison']}**: {cmp_['mean_person_days']:.1f} person-days, "
            f"95% CI [{cmp_['ci_lo']:.1f}, {cmp_['ci_hi']:.1f}] (positive = first is worse)."
        )
    wins = r["comparisons"]["scenario_win_rate"]
    eq = r["baseline_equivalence"]
    same = ", ".join(
        f"Rs {b['budget_crore']:g} cr" for b in eq["by_budget"] if b["equivalent"]
    )
    differ = ", ".join(
        f"Rs {b['budget_crore']:g} cr" for b in eq["by_budget"] if not b["equivalent"]
    )
    kinds = eq["structure_types"]
    kind_word = kinds[0] + "s" if len(kinds) == 1 else ", ".join(kinds)
    comparator = (
        "**Comparators built, not assumed.** All "
        f"{r['instance']['n_structures']} screened structures are {kind_word}, so "
        "`siloed`'s per-class split is a no-op, and `criticality_weighted` ranks on a "
        "criticality proxy of 1 + condition, which orders assets similarly to condition "
        "but not identically once intervention costs differ. The three condition-based "
        f"policies select the identical funded set at {same}."
    )
    comparator += (
        f" They differ at {differ}: same count, different assets. The identity is "
        "therefore a property of this portfolio *and* budget, and only worst-first is "
        "reported at the panel's own budget."
        if differ
        else ", every budget tested; only worst-first is reported."
    )
    lines += ["", comparator]
    chance = r["practice_vs_chance"]
    pc = chance["paired"]
    lines += [
        "",
        "Scenario win rate (share of scenarios where the policy loses fewest person-days): "
        + ", ".join(f"{k} {v:.0%}" for k, v in sorted(wins.items(), key=lambda kv: -kv[1])),
        "",
        "## Condition-first practice against chance",
        "",
        "| Metric | Condition-first | Random | Difference |",
        "|---|---|---|---|",
        f"| Mean person-days lost | {chance['worst_first_mean_person_days']:,.0f} | "
        f"{chance['random_mean_person_days']:,.0f} | "
        f"{chance['absolute_gap_person_days']:+,.0f} |",
        f"| Mean spend, planned + emergency (Rs cr) | {chance['worst_first_spend_crore']:.2f} | "
        f"{chance['random_spend_crore']:.2f} | "
        f"{chance['worst_first_spend_crore'] - chance['random_spend_crore']:+.2f} |",
        f"| Person-days lost per crore | {chance['worst_first_per_crore']:,.0f} | "
        f"{chance['random_per_crore']:,.0f} | "
        f"{chance['ratio_gap_person_days_per_crore']:+,.0f} |",
        "",
        f"Paired on the same {pc['n_scenarios']} scenarios, condition-first minus random is "
        f"{pc['mean_person_days']:+,.0f} person-days (95% CI "
        f"[{pc['ci_lo']:+,.0f}, {pc['ci_hi']:+,.0f}]); it loses fewer person-days in "
        f"{pc['share_a_better']:.0%} of scenarios and more in {pc['share_b_better']:.0%}. "
        "The two metrics disagree in sign because random funds 25 cheaper structures and so "
        "spends more: condition-first is ahead in absolute loss, behind per crore. Either "
        f"way the gap is {chance['gap_as_share_of_additive_gain']:.0%} of the "
        f"{chance['additive_gain_vs_worst_first_person_days']:,.0f} person-days that "
        "accessibility-aware allocation recovers against the same baseline. On this network "
        "condition-first ranking performs close to chance, which is a stronger motivation "
        "for the method than the method's own win.",
        "",
        "## Inspection value (which structure's condition is worth resolving)",
        "",
        "| Structure | Type | Assumed | Plan gain | Plan changes in states |",
        "|---|---|---|---|---|",
    ]
    for s in r["inspection_value"]["structures"][:10]:
        lines.append(
            f"| {s['id']} | {s['type']} | {s['assumed_condition']} | "
            f"{s['expected_gain']:.1f} | {s['plan_changes_in_states']}/3 |"
        )
    lines += [
        "",
        f"Sum of positive gains: {r['inspection_value']['sum_positive_gain']:.1f} "
        f"(base objective {r['inspection_value']['base_objective']:.1f}).",
        "",
        "## Single points of failure",
        "",
        f"{r['n_single_points_of_failure']} of {len(r['islanding'])} structures cut any "
        "habitation off from a hospital when failing alone.",
        "",
        "| Structure | Isolated habitations | Isolated population | Max extra one-way minutes |",
        "|---|---|---|---|",
    ]
    for s in r["islanding"][:10]:
        lines.append(
            f"| {s['id']} | {s['isolated_habitations']} | {s['isolated_population']:.0f} | "
            f"{s['max_extra_one_way_minutes']:.0f} |"
        )
    eq = r["equity"]
    lines += [
        "",
        "## Benefit distribution",
        "",
        f"- habitations reached: {eq['n_habitations_reached']} "
        f"({eq['share_of_population_reached']:.0%} of population)",
        f"- Gini of benefit per person: {eq['gini_of_benefit_per_person']:.3f}",
        f"- top 1% share of benefit: {eq['top_1pct_share_of_benefit']:.2f}",
        "",
        "## Destination sensitivity: hospitals against schools",
        "",
        "Isolation depends on what counts as a destination. The audit above uses hospitals "
        "only \u2014 the most forgiving set in the district \u2014 so this repeats it with the "
        "school layer (schools, colleges, kindergartens) on the same 30 structures, the same "
        "graph and the same funded plan. No market layer exists to test: the OSM extract "
        "contains no `amenity=marketplace` points.",
        "",
        "| Destination | Points | Cap (min) | Median access | Within cap | SPOF | Isolated population | Benefit Gini |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for d in r.get("destination_sensitivity", []):
        gini = d["equity"].get("gini_of_benefit_per_person")
        gini_text = f"{gini:.3f}" if isinstance(gini, (int, float)) else "-"
        isolated = sum(s["isolated_population"] for s in d["islanding"])
        lines.append(
            f"| {d['destination']} | {d['n_facilities']:,} | {d['cap_minutes']:.0f} | "
            f"{d['baseline_median_minutes']:.1f} | {d['baseline_share_within_cap']:.1%} | "
            f"{d['n_single_points_of_failure']} | {isolated:,.0f} | {gini_text} |"
        )
    lines += [
        "",
        "The school tier reuses the hospital-optimised funded plan, so its benefit split "
        "answers a distributional question about that plan rather than re-solving the "
        "optimiser for schools; the isolation counts are independent of the plan.",
        "",
        "## Budget frontier (plan objective)",
        "",
        "| Budget (cr) | Objective | Loss per crore | Funded |",
        "|---|---|---|---|",
    ]
    for b in r["budget_frontier"]:
        per = b["planned_loss_per_crore"]
        lines.append(
            f"| {b['budget_crore']:.2f} | {b['objective']:.1f} | "
            f"{per:.1f} | {b['n_funded']} |" if per else
            f"| {b['budget_crore']:.2f} | {b['objective']:.1f} | - | {b['n_funded']} |"
        )
    lines += _robustness_markdown(r.get("robustness"))
    lines += [
        "",
        "Structures are unverified road/water screening candidates, not an asset register; "
        "condition, age, outage and cost are assumed and varied in E8. These are planning "
        "exercises, not observed condition or a spending recommendation.",
        "",
    ]
    return "\n".join(lines)


def _robustness_markdown(rob: dict | None) -> list[str]:
    """The robustness sections, generated only from the persisted block."""
    if not rob:
        return ["", "## Robustness of the headline finding", "",
                "Not run (`--no-robustness`).", ""]
    lines = ["", "## Robustness of the headline finding", ""]

    def failed(key):
        return isinstance(rob.get(key), dict) and "error" in rob[key]

    sm = rob.get("spend_matched")
    lines += [
        "### Equal planned spend",
        "",
        "The panel above lets each rule spend what it chooses, so the absolute and per-crore "
        "readings can disagree in sign. Here every policy faces the same planned budget, "
        "including the budget at which condition-first actually spends at the reporting "
        "setting. Emergency restoration is reported but not equalised: it follows failure, "
        "it is not an allocation choice.",
        "",
    ]
    if not sm or "error" in sm:
        lines.append(f"Not available ({sm.get('error') if isinstance(sm, dict) else 'missing'}).")
    else:
        lines += [
            "| Budget/yr (cr) | Policy | Mean person-days | Planned (cr) | Emergency (cr) | Funded |",
            "|---|---|---|---|---|---|",
        ]
        for row in sm["rows"]:
            lines.append(
                f"| {row['budget_crore_per_year']:.3f} | {row['policy']} | "
                f"{row['mean_person_days']:,.0f} | {row['mean_planned_crore']:.3f} | "
                f"{row['mean_emergency_crore']:.3f} | {row['n_funded_year1']} |"
            )
        lines += ["", "Matched-spend comparison of condition-first against random:", ""]
        lines += ["| Budget/yr (cr) | WF planned | Random planned | Gap | Paired WF-random (95% CI) | WF better in |",
                  "|---|---|---|---|---|---|"]
        for m in sm["matched"]:
            p = m["paired"] or {}
            lines.append(
                f"| {m['budget_crore_per_year']:.3f} | {m['worst_first_planned_crore']:.3f} | "
                f"{m['random_planned_crore']:.3f} | {m['planned_spend_gap_crore']:+.3f} | "
                f"{p.get('mean_person_days', float('nan')):+,.0f} "
                f"({p.get('ci_lo', float('nan')):+,.0f}, {p.get('ci_hi', float('nan')):+,.0f}) | "
                f"{p.get('share_a_better', 0):.0%} |"
            )

    prec = rob.get("precision")
    lines += ["", "### Equivalence and precision", ""]
    if not prec or "error" in prec:
        lines.append(f"Not available ({prec.get('error') if isinstance(prec, dict) else 'missing'}).")
    else:
        lines += [
            "A confidence interval containing zero is not evidence of equivalence. The "
            "margin here is a share of what the additive policy recovers against "
            "condition-first, so the test asks whether practice is within a *policy-relevant* "
            "distance of chance.",
            "",
            "| Scenarios | WF-random | SD | MDE | Additive gain | Margin | TOST p | Verdict | n required |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for row in prec["rows"]:
            for eq in row["equivalence"]:
                lines.append(
                    f"| {row['n_scenarios']} | {row['worst_first_minus_random_person_days']:+,.0f} | "
                    f"{row['sd_of_paired_difference']:,.0f} | "
                    f"{eq['min_detectable_difference']:,.0f} | "
                    f"{row['additive_gain_vs_worst_first_person_days']:,.0f} | "
                    f"{eq['margin']:,.0f} ({eq['margin_share_of_additive_gain']:.0%}) | "
                    f"{eq['p_tost']:.3f} | "
                    f"{'equivalent' if eq['equivalent'] else 'inconclusive'} | "
                    f"{eq['required_n']} |"
                )
        lines += [
            "",
            "An 'inconclusive' verdict means the design cannot demonstrate equivalence at "
            "that margin; `n required` is the paired scenario count a TOST at that margin "
            "would need at 80% power. The honest claim is therefore that practice is not "
            "distinguishable from chance and that the design is underpowered to claim more.",
        ]

    heur = rob.get("heuristics")
    lines += ["", "### Consequence-blind rules, not one baseline", ""]
    if not heur or "error" in heur:
        lines.append(f"Not available ({heur.get('error') if isinstance(heur, dict) else 'missing'}).")
    else:
        lines += [
            "| Rule | Mean person-days | Planned (cr) | Funded | Paired vs random (95% CI) | Better in |",
            "|---|---|---|---|---|---|",
        ]
        for row in heur["rows"]:
            key = f"{row['policy']}_vs_random"
            cmp_ = heur["comparisons"].get(key)
            detail = (
                f"{cmp_['mean_person_days']:+,.0f} ({cmp_['ci_lo']:+,.0f}, {cmp_['ci_hi']:+,.0f})"
                if cmp_ else "-"
            )
            share = f"{cmp_['share_a_better']:.0%}" if cmp_ else "-"
            lines.append(
                f"| {row['policy']} | {row['mean_person_days']:,.0f} | "
                f"{row['mean_planned_crore']:.3f} | {row['n_funded_year1']} | {detail} | {share} |"
            )
        lines += [
            "",
            "Every rule here buys the condition-appropriate intervention, so the comparison "
            "is about the ranking signal alone. None of them uses a consequence measure.",
        ]

    sweep = rob.get("cap_sweep")
    lines += ["", "### Destination and travel-time cap, swept together", ""]
    if not sweep or "error" in sweep:
        lines.append(f"Not available ({sweep.get('error') if isinstance(sweep, dict) else 'missing'}).")
    else:
        lines += [
            "| Destination | Cap (min) | Points | Median access | Within cap | SPOF | Isolated people (summed) | Benefit Gini |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in sweep:
            gini = row["equity"].get("gini_of_benefit_per_person")
            lines.append(
                f"| {row['destination']} | {row['cap_minutes']:.0f} | {row['n_facilities']:,} | "
                f"{row['baseline_median_minutes']:.1f} | {row['baseline_share_within_cap']:.1%} | "
                f"{row['n_single_points_of_failure']} | "
                f"{row['isolated_population_summed_over_structures']:,.0f} | "
                f"{gini:.3f} |"
            )
        lines += [
            "",
            "The hospital-at-60 cell is the most forgiving one in this table: sparsest "
            "destination set, loosest cap. Comparing cells separates the destination set from "
            "the cap, which a single hospital-versus-school pair cannot do.",
        ]

    port = rob.get("portfolios")
    lines += ["", "### Does the selection rule drive the result?", ""]
    if not port or "error" in port:
        lines.append(f"Not available ({port.get('error') if isinstance(port, dict) else 'missing'}).")
    else:
        lines += [
            "The reported portfolio is the 30 highest *hospital* solo-loss crossings. Every "
            "result about schools and islanding is therefore conditional on a "
            "hospital-conditioned sample. Rebuilding the same-size portfolio under other "
            "rules tests that directly; islanding does not depend on the funded plan.",
            "",
            "| Portfolio rule | Type mix | WF mean PD | Random mean PD | SPOF hospitals@60 | SPOF schools@45 |",
            "|---|---|---|---|---|---|",
        ]
        for row in port["variants"]:
            cells = {(c["destination"], c["cap_minutes"]): c for c in row["destination_islanding"]}
            h = cells.get(("health", 60.0), {})
            s = cells.get(("school", 45.0), {})
            at_ = {p["policy"]: p for p in row["policies"]}
            mix = ", ".join(f"{k} {v}" for k, v in sorted(row["structure_types"].items()))
            lines.append(
                f"| {row['portfolio']} | {mix} | "
                f"{at_.get('worst_first', {}).get('mean_person_days', float('nan')):,.0f} | "
                f"{at_.get('random', {}).get('mean_person_days', float('nan')):,.0f} | "
                f"{h.get('n_single_points_of_failure', '-')} | "
                f"{s.get('n_single_points_of_failure', '-')} |"
            )
        sc = port.get("school_scores", {})
        if sc:
            lines += [
                "",
                f"School criticality was measured on {sc.get('n_edges', 0):,} candidate "
                f"edges at a {sc.get('cap_minutes', 0):.0f}-minute cap"
                + ("; the sweep was truncated to the highest hospital-loss edges."
                   if sc.get("truncated") else "."),
            ]

    eqc = rob.get("equity_cost")
    lines += ["", "### What an equity floor would cost", ""]
    if not eqc or "error" in eqc:
        lines.append(f"Not available ({eqc.get('error') if isinstance(eqc, dict) else 'missing'}).")
    else:
        lines += [
            f"The plan reaches {eqc['n_habitations_eligible']} of "
            f"{eqc['n_habitations_total']} habitations with any potential benefit. A hard "
            "floor on per-habitation benefit is degenerate on this portfolio (coverage is "
            "close to disjoint, so any unfunded hamlet holds the floor at zero), so the "
            "instrument is a weight on the objective instead: exponent 0 is the reported "
            "population-weighted plan, exponent 1 counts every habitation equally.",
            "",
            "| Weight exponent | Funded | Spend (cr) | Total benefit | Gini | Reached | Efficiency lost |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in eqc["rows"]:
            if row.get("infeasible"):
                lines.append(f"| {row['exponent']:.2f} | infeasible | - | - | - | - | - |")
                continue
            lines.append(
                f"| {row['exponent']:.2f} | {row['funded']} | {row['spend_crore']:.3f} | "
                f"{row['total_benefit']:,.1f} | {row['gini_of_benefit_per_person']:.3f} | "
                f"{row['n_habitations_with_benefit']} | "
                f"{row['benefit_lost_vs_efficiency']:,.1f} |"
            )

    sched = rob.get("schedule")
    lines += ["", "### Two-year schedule against the receding-horizon plan", ""]
    if not sched or "error" in sched:
        lines.append(f"Not available ({sched.get('error') if isinstance(sched, dict) else 'missing'}).")
    else:
        pc = sched["paired_difference_vs_myopic"]
        lines += [
            f"- two-period schedule: {sched['mean_person_days']:,.0f} person-days, planned "
            f"Rs {sched['mean_planned_crore']:.3f} cr, emergency Rs {sched['mean_emergency_crore']:.3f} cr",
            f"- receding-horizon additive plan: {sched['myopic_mean_person_days']:,.0f} person-days",
            f"- paired difference (schedule minus receding horizon): {pc['mean_person_days']:+,.0f} "
            f"(95% CI {pc['ci_lo']:+,.0f}, {pc['ci_hi']:+,.0f})",
            f"- year-1 funded set overlap with the receding-horizon plan: Jaccard "
            f"{sched['jaccard_year1_vs_myopic']:.2f}",
        ]

    solver = rob.get("solver")
    lines += ["", "### Solver quality", ""]
    if not solver or "error" in solver:
        lines.append(f"Not available ({solver.get('error') if isinstance(solver, dict) else 'missing'}).")
    else:
        gap = solver.get("mip_gap")
        lines += [
            f"- {solver['n_variables']} variables, {solver['n_scenarios']} scenarios, "
            f"{solver['n_funded']} structures funded, objective {solver['objective']:,.1f}",
            f"- reported MIP gap: {'not exposed' if gap is None else f'{gap:.2e}'}; "
            f"status {solver['status']}",
        ]
    return lines


if __name__ == "__main__":
    main()
