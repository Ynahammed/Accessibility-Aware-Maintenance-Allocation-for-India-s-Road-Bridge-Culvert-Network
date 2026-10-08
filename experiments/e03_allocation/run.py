"""E3 — does accessibility-aware allocation beat condition-based ranking?

Runs every policy on one shared scenario set (paired), reports the plan's primary metric
(person-days of access lost per Rs crore spent over the horizon) plus tail loss (CVaR),
and a paired bootstrap of the proposed method against worst-first.

    python experiments/e03_allocation/run.py --config experiments/e03_allocation/config.json

Everything is seeded and reproducible; results land in ``results.json`` and ``results.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rra.assumptions import AssumptionRegister  # noqa: E402
from rra.evaluate import metrics, stats  # noqa: E402
from rra.network.synthetic import make_district  # noqa: E402
from rra.optimize.cvar import cvar  # noqa: E402
from rra import pipeline  # noqa: E402
from rra.simulator import policies, step  # noqa: E402
from rra.simulator.optimized_policies import (  # noqa: E402
    AdditiveMilpPolicy,
    NetworkAwarePolicy,
)

DEFAULTS = {
    "seed": 0,
    "scenarios": 40,
    "years": 5,
    "optimizer_samples": 40,
    "district": {"n_junctions": 24, "n_habitations": 14, "n_structures": 10},
    "budget_crore": 100.0,
    "crew_days": 500.0,
    "cvar_alpha": 0.1,
}


def load_config(path: str | None) -> dict:
    cfg = dict(DEFAULTS)
    if path:
        cfg.update(json.loads(Path(path).read_text()))
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)

    t0 = time.time()
    register = AssumptionRegister.default()
    district = make_district(
        n_junctions=cfg["district"]["n_junctions"],
        n_habitations=cfg["district"]["n_habitations"],
        n_structures=cfg["district"]["n_structures"],
        seed=cfg["seed"],
    )
    district.budget_crore = cfg["budget_crore"]
    district.crew_days = cfg["crew_days"]

    models = pipeline.build_models(district, register, seed=cfg["seed"])
    world = pipeline.build_world(district, register, seed=cfg["seed"])
    asset_ids = list(world.assets)

    rng = np.random.default_rng(cfg["seed"])
    n_assets = len(asset_ids)
    rain = np.exp(rng.normal(0.0, 0.4, size=(cfg["scenarios"], cfg["years"], n_assets)))
    scen = step.make_scenarios(asset_ids, cfg["years"], cfg["scenarios"], rng, rain=rain)

    opt_rain = np.exp(
        np.random.default_rng(cfg["seed"] + 1).normal(
            0.0, 0.4, size=(cfg["optimizer_samples"], n_assets)
        )
    )

    policy_list = list(policies.BASELINE_POLICIES) + [
        AdditiveMilpPolicy(models, opt_rain, seed=cfg["seed"]),
        NetworkAwarePolicy(models, opt_rain, seed=cfg["seed"]),
    ]

    outcomes = {}
    for p in policy_list:
        outcomes[getattr(p, "name", "policy")] = step.run(p, world, scen, models)

    # primary metric and tail loss
    rows = []
    for name, out in outcomes.items():
        pd = out.person_days
        spend = out.spend
        rows.append(
            {
                "policy": name,
                "mean_person_days": float(pd.mean()),
                "mean_spend_crore": float(spend.mean()),
                "person_days_per_crore": metrics.access_lost_per_crore(pd.sum(), spend.sum()),
                "cvar_person_days": cvar(pd, cfg["cvar_alpha"]),
            }
        )
    rows.sort(key=lambda r: r["person_days_per_crore"])

    # paired comparison: proposed vs worst-first
    comparison = None
    if "network_aware" in outcomes and "worst_first" in outcomes:
        ci = stats.paired_bootstrap_ci(
            outcomes["worst_first"].person_days,
            outcomes["network_aware"].person_days,
            rng=cfg["seed"],
        )
        comparison = {
            "metric": "person_days (worst_first - network_aware), positive = proposed better",
            "mean": ci.mean,
            "ci_lo": ci.lo,
            "ci_hi": ci.hi,
        }

    elapsed = time.time() - t0
    result = {
        "config": cfg,
        "n_habitations": len(district.habitations),
        "n_assets": n_assets,
        "policies": rows,
        "comparison_worst_first_vs_network_aware": comparison,
        "elapsed_seconds": elapsed,
    }

    out_dir = Path(__file__).resolve().parent
    (out_dir / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out_dir / "results.md").write_text(_markdown(result), encoding="utf-8")
    print(_markdown(result))
    print(f"\n(wrote results.json / results.md in {elapsed:.1f}s)")


def _markdown(result: dict) -> str:
    lines = [
        "# E3 — accessibility-aware vs condition-based allocation",
        "",
        f"- district: {result['n_habitations']} habitations, {result['n_assets']} structures",
        f"- scenarios: {result['config']['scenarios']}, years: {result['config']['years']}",
        f"- budget: Rs {result['config']['budget_crore']} crore, "
        f"crew: {result['config']['crew_days']} crew-days",
        "",
        "| Policy | Mean person-days | Mean spend (cr) | Person-days per crore | CVaR |",
        "|---|---|---|---|---|",
    ]
    for r in result["policies"]:
        lines.append(
            f"| {r['policy']} | {r['mean_person_days']:.1f} | {r['mean_spend_crore']:.2f} | "
            f"{r['person_days_per_crore']:.1f} | {r['cvar_person_days']:.1f} |"
        )
    c = result.get("comparison_worst_first_vs_network_aware")
    if c:
        lines += [
            "",
            f"**Paired (same scenarios):** worst-first minus network-aware = {c['mean']:.1f} "
            f"person-days, 95% CI [{c['ci_lo']:.1f}, {c['ci_hi']:.1f}]. "
            f"Positive = the proposed method loses fewer person-days.",
        ]
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
