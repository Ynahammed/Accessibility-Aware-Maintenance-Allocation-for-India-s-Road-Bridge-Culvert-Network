"""E8 — how robust are the conclusions? (plan sections 6 and 9)

Draws assumption sets from the register, runs the baseline policies plus the additive and
network-aware optimizers under each set, and reports:

* the primary metric (person-days of access lost per Rs crore) per draw,
* each policy's **win rate** (fraction of assumption sets where it is best),
* each policy's **regret** (loss gap to the best policy under that set).

The headline claim the plan wants is a policy that is *near-best across the whole range*,
not one that wins under a single setting.

    python experiments/e08_robustness/run.py --config experiments/e08_robustness/config.json
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
from rra.evaluate import metrics, regret  # noqa: E402
from rra.network.build import class_speeds_from_register  # noqa: E402
from rra.network.synthetic import make_district  # noqa: E402
from rra import pipeline  # noqa: E402
from rra.simulator import policies, step  # noqa: E402
from rra.simulator.optimized_policies import (  # noqa: E402
    AdditiveMilpPolicy,
    NetworkAwarePolicy,
)

DEFAULTS = {
    "seed": 0,
    "n_draws": 8,
    "scenarios": 20,
    "years": 4,
    "optimizer_samples": 20,
    "district": {"n_junctions": 16, "n_habitations": 10, "n_structures": 6},
    "budget_crore": 60.0,
    "crew_days": 300.0,
    "cvar_alpha": 0.1,
}


def load_config(path: str | None) -> dict:
    cfg = dict(DEFAULTS)
    if path:
        cfg.update(json.loads(Path(path).read_text()))
    return cfg


def run_draw(cfg: dict, register: AssumptionRegister, draw: int) -> dict:
    seed = cfg["seed"] + draw
    district = make_district(
        n_junctions=cfg["district"]["n_junctions"],
        n_habitations=cfg["district"]["n_habitations"],
        n_structures=cfg["district"]["n_structures"],
        seed=cfg["seed"],
        class_speeds=class_speeds_from_register(register),
    )
    district.budget_crore = cfg["budget_crore"]
    district.crew_days = cfg["crew_days"]
    models = pipeline.build_models(district, register, seed=cfg["seed"])
    world = pipeline.build_world(district, register, seed=cfg["seed"])
    asset_ids = list(world.assets)
    n_assets = len(asset_ids)

    rng = np.random.default_rng(seed)
    rain = np.exp(rng.normal(0.0, 0.4, size=(cfg["scenarios"], cfg["years"], n_assets)))
    scen = step.make_scenarios(asset_ids, cfg["years"], cfg["scenarios"], rng, rain=rain)
    opt_rain = np.exp(
        np.random.default_rng(seed + 1000).normal(
            0.0, 0.4, size=(cfg["optimizer_samples"], n_assets)
        )
    )

    policy_list = [
        policies.DoNothingPolicy(),
        policies.WorstFirstPolicy(),
        policies.BenefitCostPolicy(),
        AdditiveMilpPolicy(models, opt_rain, seed=seed),
        NetworkAwarePolicy(models, opt_rain, seed=seed),
    ]
    metric = {}
    for p in policy_list:
        out = step.run(p, world, scen, models)
        metric[getattr(p, "name", "policy")] = metrics.access_lost_per_crore(
            out.person_days.sum(), out.spend.sum()
        )
    return metric


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)

    t0 = time.time()
    register = AssumptionRegister.default()
    draws = register.sample(cfg["seed"], n=cfg["n_draws"])

    policy_names = ["do_nothing", "worst_first", "benefit_cost", "additive_milp",
                    "network_aware"]
    per_draw = []
    for d, values in enumerate(draws):
        reg = register.with_values(values)
        row = run_draw(cfg, reg, d)
        per_draw.append(row)

    losses = np.array([[row[name] for row in per_draw] for name in policy_names])
    rob = regret.analyse(losses, policy_names)

    result = {
        "config": cfg,
        "policies": policy_names,
        "per_draw_metric": {name: losses[i].tolist() for i, name in enumerate(policy_names)},
        "win_rate": {n: float(w) for n, w in zip(policy_names, rob.win_rate)},
        "mean_regret": {n: float(v) for n, v in zip(policy_names, rob.mean_regret)},
        "max_regret": {n: float(v) for n, v in zip(policy_names, rob.max_regret)},
        "elapsed_seconds": time.time() - t0,
    }

    out_dir = Path(__file__).resolve().parent
    (out_dir / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out_dir / "results.md").write_text(_markdown(result), encoding="utf-8")
    print(_markdown(result))
    print(f"\n(wrote results.json / results.md in {result['elapsed_seconds']:.1f}s)")


def _markdown(result: dict) -> str:
    names = result["policies"]
    lines = [
        "# E8 — robustness and regret across the assumptions register",
        "",
        f"- assumption sets sampled: {result['config']['n_draws']}",
        f"- scenarios x years: {result['config']['scenarios']} x {result['config']['years']}",
        f"- budget: Rs {result['config']['budget_crore']} crore",
        "",
        "| Policy | Win rate | Mean regret | Max regret |",
        "|---|---|---|---|",
    ]
    for n in names:
        lines.append(
            f"| {n} | {result['win_rate'][n]:.2f} | {result['mean_regret'][n]:.2f} | "
            f"{result['max_regret'][n]:.2f} |"
        )
    lines += ["", "## Primary metric per assumption set (person-days per crore)", ""]
    header = "| Assumption set | " + " | ".join(names) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(names) + 1))
    n_draws = len(next(iter(result["per_draw_metric"].values())))
    for d in range(n_draws):
        cells = " | ".join(f"{result['per_draw_metric'][n][d]:.1f}" for n in names)
        winner = min(names, key=lambda n: result["per_draw_metric"][n][d])
        lines.append(f"| {d} | {cells} | ({winner})")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
