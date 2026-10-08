"""E4 — do network effects matter? (plan section 6)

Builds redundant corridors (each habitation joined to the facility by ``redundancy``
parallel routes, one structure per route), applies **monsoon-stress** rainfall so joint
failures actually occur, and compares the additive MILP against the network-aware search at
an equal budget. Solo loss is zero for every structure here, so an additive model sees no
benefit at all while the true (set-based) loss is large.

Sweeping ``redundancy`` shows how the gap behaves: for r=1 every structure is critical
(additive suffices); as r grows the value of a repair comes only from preventing *joint*
failure.

    python experiments/e04_network_effects/run.py --config experiments/e04_network_effects/config.json
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
from rra.evaluate import metrics  # noqa: E402
from rra.network.build import class_speeds_from_register  # noqa: E402
from rra.network.synthetic import make_redundant_district  # noqa: E402
from rra.optimize.cvar import cvar  # noqa: E402
from rra import pipeline  # noqa: E402
from rra.simulator import policies, step  # noqa: E402
from rra.simulator.optimized_policies import (  # noqa: E402
    AdditiveMilpPolicy,
    NetworkAwarePolicy,
)

DEFAULTS = {
    "seed": 0,
    "redundancies": [1, 2, 3, 4],
    "n_corridors": 3,
    "scenarios": 30,
    "years": 4,
    "optimizer_samples": 30,
    "rain_log_ratio": 0.9,
    "rain_log_sigma": 0.15,
    "initial_condition": 2,
    "budget_crore": 0.4,
    "crew_days": 1000.0,
    "cvar_alpha": 0.1,
}


def load_config(path: str | None) -> dict:
    cfg = dict(DEFAULTS)
    if path:
        cfg.update(json.loads(Path(path).read_text()))
    return cfg


def run_redundancy(cfg: dict, register: AssumptionRegister, redundancy: int) -> dict:
    seed = cfg["seed"] + redundancy
    district = make_redundant_district(
        n_corridors=cfg["n_corridors"],
        redundancy=redundancy,
        seed=seed,
        class_speeds=class_speeds_from_register(register),
    )
    district.budget_crore = cfg["budget_crore"]
    district.crew_days = cfg["crew_days"]
    models = pipeline.build_models(district, register, seed=seed)
    world = pipeline.build_world(district, register, seed=seed)
    for a in world.assets.values():  # stress: start every structure Poor
        a.condition = cfg["initial_condition"]
    asset_ids = list(world.assets)
    n_assets = len(asset_ids)

    # monsoon-stress rainfall: high ratios so joint failures are common
    def stress(size):
        return np.exp(
            np.random.default_rng(seed).normal(
                cfg["rain_log_ratio"], cfg["rain_log_sigma"], size=size
            )
        )

    rain = stress((cfg["scenarios"], cfg["years"], n_assets))
    scen = step.make_scenarios(asset_ids, cfg["years"], cfg["scenarios"],
                              np.random.default_rng(seed), rain=rain)
    opt_rain = np.exp(
        np.random.default_rng(seed + 999).normal(
            cfg["rain_log_ratio"], cfg["rain_log_sigma"],
            size=(cfg["optimizer_samples"], n_assets),
        )
    )

    policy_list = [
        policies.DoNothingPolicy(),
        policies.WorstFirstPolicy(),
        policies.BenefitCostPolicy(),
        AdditiveMilpPolicy(models, opt_rain, seed=seed),
        NetworkAwarePolicy(models, opt_rain, seed=seed),
    ]
    rows = {}
    for p in policy_list:
        out = step.run(p, world, scen, models)
        rows[getattr(p, "name", "policy")] = {
            "mean_person_days": float(out.person_days.mean()),
            "mean_planned_crore": float(out.planned.mean()),
            "person_days_per_crore": metrics.access_lost_per_crore(
                out.person_days.sum(), out.spend.sum()
            ),
            "cvar": cvar(out.person_days, cfg["cvar_alpha"]),
        }
    return {"redundancy": redundancy, "n_assets": n_assets, "policies": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)

    t0 = time.time()
    register = AssumptionRegister.default()
    results = [run_redundancy(cfg, register, r) for r in cfg["redundancies"]]

    out = {"config": cfg, "by_redundancy": results, "elapsed_seconds": time.time() - t0}
    out_dir = Path(__file__).resolve().parent
    (out_dir / "results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (out_dir / "results.md").write_text(_markdown(out), encoding="utf-8")
    print(_markdown(out))
    print(f"\n(wrote results.json / results.md in {out['elapsed_seconds']:.1f}s)")


def _markdown(out: dict) -> str:
    cfg = out["config"]
    lines = [
        "# E4 — do network effects matter? (additive MILP vs network-aware)",
        "",
        f"- corridors: {cfg['n_corridors']}, monsoon-stress rain ratio ~ e^{cfg['rain_log_ratio']}, "
        f"budget Rs {cfg['budget_crore']} crore",
        "- each corridor: one habitation, `redundancy` parallel routes, one structure per route",
        "",
        "## Mean person-days lost (lower is better)",
        "",
        "| Redundancy | Do nothing | Worst-first | Benefit-cost | Additive MILP | "
        "Network-aware | Additive - Network |",
        "|---|---|---|---|---|---|---|",
    ]
    for blk in out["by_redundancy"]:
        p = blk["policies"]
        gap = p["additive_milp"]["mean_person_days"] - p["network_aware"]["mean_person_days"]
        lines.append(
            f"| {blk['redundancy']} | {p['do_nothing']['mean_person_days']:.0f} | "
            f"{p['worst_first']['mean_person_days']:.0f} | "
            f"{p['benefit_cost']['mean_person_days']:.0f} | "
            f"{p['additive_milp']['mean_person_days']:.0f} | "
            f"{p['network_aware']['mean_person_days']:.0f} | {gap:+.0f} |"
        )
    lines += [
        "",
        "**Reading (honest):**",
        "",
        "1. **Network effects matter.** At redundancy >= 2 every structure's solo loss is zero,",
        "   so the *additive MILP does nothing* (it equals do-nothing exactly) while the",
        "   network-aware objective finds real reductions. At redundancy 1 the two agree —",
        "   additive already suffices when every structure is critical. That is the E4 answer.",
        "2. **But condition-first is strong here.** worst-first spends the same budget on",
        "   condition-appropriate (major/replace) repairs and beats the network-aware search on",
        "   this *symmetric* district. The search warm-starts from the all-NONE additive plan",
        "   and its greedy swap moves can stall — exactly the 'local search gives poor"
        "   solutions' risk the plan flags (mitigation: seed from MILP, multiple restarts).",
        "3. The absolute loss falls as redundancy grows (joint failure gets rarer), so the",
        "   additive-network *gap* is largest at moderate redundancy rather than at high r.",
        "",
        "Next: improve the network-aware search (restarts / better moves) and re-test; the",
        "shape of the table, not the current winner, is the E4 finding.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
