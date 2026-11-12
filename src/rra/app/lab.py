"""Live allocation lab: paired policy experiments and consequence queries.

Five policies are evaluated on the **same** scenario draws (common random numbers), so
differences are attributable to the allocation rule. Results are cached per parameter
set: the simulation is CPU-bound and deterministic, so a repeat request is free.
"""

from __future__ import annotations

import json
import threading
import time

import numpy as np

from rra import pipeline
from rra.deterioration.markov import STATES
from rra.evaluate import metrics, stats
from rra.network.build import class_speeds_from_register
from rra.network.synthetic import make_district, make_redundant_district
from rra.optimize.cvar import cvar
from rra.simulator import policies, step
from rra.simulator.optimized_policies import AdditiveMilpPolicy, NetworkAwarePolicy

from .districts import build_world_models, get_spec, summarize
from .register import live_register

POLICY_ORDER = (
    "do_nothing",
    "worst_first",
    "benefit_cost",
    "additive_milp",
    "network_aware",
)

DEFAULTS = {
    "preset": "generic",  # generic | redundant
    "budget_crore": 0.6,
    "stress": 0.0,  # mean log rainfall ratio (monsoon stress)
    "seed": 0,
    "scenarios": 8,
    "years": 3,
    "redundancy": 2,
}

_RUN_LOCK = threading.Lock()
_CACHE: dict[str, dict] = {}
_CACHE_MAX = 64


def _clamp(name: str, value, lo, hi, cast=float):
    try:
        v = cast(value)
    except (TypeError, ValueError):
        return DEFAULTS.get(name, lo)
    return max(lo, min(hi, v))


def normalize_params(body: dict) -> dict:
    """Validate/clamp client input so a bad request can never crash a run."""
    body = body or {}
    p = dict(DEFAULTS)
    preset = body.get("preset")
    p["preset"] = preset if preset in ("generic", "redundant") else "generic"
    p["budget_crore"] = _clamp("budget_crore", body.get("budget_crore", p["budget_crore"]), 0.0, 5.0)
    p["stress"] = _clamp("stress", body.get("stress", p["stress"]), -1.0, 2.0)
    p["seed"] = _clamp("seed", body.get("seed", p["seed"]), 0, 999, cast=int)
    p["scenarios"] = _clamp("scenarios", body.get("scenarios", p["scenarios"]), 1, 32, cast=int)
    p["years"] = _clamp("years", body.get("years", p["years"]), 1, 5, cast=int)
    p["redundancy"] = _clamp("redundancy", body.get("redundancy", p["redundancy"]), 1, 4, cast=int)
    return p


def district_id_for(p: dict) -> str:
    """Map lab parameters to a registered district id."""
    if p["preset"] == "redundant":
        return f"synth-redundant-r{p['redundancy']}"
    return "synth-generic"


class _RecordingPolicy:
    """Wrap a policy and capture its first-year plan for the map overlay."""

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.plan: dict | None = None

    def propose(self, assets, ctx):
        chosen = self.inner.propose(assets, ctx)
        if self.plan is None:
            self.plan = {aid: opt.value for aid, opt in chosen.items()}
        return chosen


def _map_payload(district, world, models) -> dict:
    """Serialise the graph and assets for the SVG renderer in the browser."""
    nodes = []
    for n, d in district.graph.nodes(data=True):
        x, y = d.get("pos", (0.0, 0.0))
        rec = {"id": str(n), "x": float(x), "y": float(y), "kind": d.get("kind", "junction")}
        if n in district.habitations:
            rec["population"] = float(district.habitations[n])
        if d.get("facility_type"):
            rec["facility_type"] = d["facility_type"]
        if d.get("structure_type"):
            rec["structure_type"] = d["structure_type"]
        nodes.append(rec)
    edges = [{"u": str(u), "v": str(v)} for u, v in district.graph.edges()]
    structures = []
    for aid, node, s_type in district.structures:
        a = world.assets[aid]
        structures.append(
            {
                "id": aid,
                "node": str(node),
                "type": s_type,
                "condition": int(a.condition),
                "state": STATES[int(a.condition)],
                "age": int(a.age),
                "solo_loss": float(models.acc.loss(failed_nodes=[a.node])),
            }
        )
    habitations = {str(k): float(v) for k, v in district.habitations.items()}
    facilities = {k: [str(n) for n in v] for k, v in district.facilities.items()}
    return {
        "nodes": nodes,
        "edges": edges,
        "structures": structures,
        "habitations": habitations,
        "facilities": facilities,
    }


def run_experiment(body: dict) -> dict:
    """One paired comparison of five policies on shared scenarios (CRN)."""
    p = normalize_params(body)
    live = live_register()
    # The register is an input: a newly ingested reply must not be served a cached run
    # computed under the previous assumptions.
    key = json.dumps(p, sort_keys=True) + "|" + live.fingerprint
    with _RUN_LOCK:
        if key in _CACHE:
            return _CACHE[key]
        t0 = time.time()
        out = _run_experiment(p, live)
        out["elapsed_seconds"] = round(time.time() - t0, 2)
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = out
        return out


def _run_experiment(p: dict, live=None) -> dict:
    live = live if live is not None else live_register()
    register = live.register
    seed, stress = p["seed"], p["stress"]
    if p["preset"] == "generic":
        district = make_district(n_junctions=24, n_habitations=14, n_structures=10, seed=seed)
        district.budget_crore = p["budget_crore"]
        district.crew_days = 400.0
        sigma = 0.4
    else:
        district = make_redundant_district(
            n_corridors=3,
            redundancy=p["redundancy"],
            seed=seed,
            class_speeds=class_speeds_from_register(register),
        )
        district.budget_crore = p["budget_crore"]
        district.crew_days = 1000.0
        sigma = 0.15

    models = pipeline.build_models(district, register, seed=seed, sor=live.sor)
    world = pipeline.build_world(district, register, seed=seed)
    if p["preset"] == "redundant":
        for a in world.assets.values():  # monsoon-stress bed: start Poor, like E4
            a.condition = 2

    asset_ids = list(world.assets)
    n_assets = len(asset_ids)
    rng = np.random.default_rng(seed + 7)
    rain = np.exp(rng.normal(stress, sigma, size=(p["scenarios"], p["years"], n_assets)))
    scen = step.make_scenarios(asset_ids, p["years"], p["scenarios"], rng, rain=rain)
    opt_rain = np.exp(
        np.random.default_rng(seed + 999).normal(stress, sigma, size=(p["scenarios"], n_assets))
    )

    policy_list = [
        _RecordingPolicy(policies.DoNothingPolicy()),
        _RecordingPolicy(policies.WorstFirstPolicy()),
        _RecordingPolicy(policies.BenefitCostPolicy()),
        _RecordingPolicy(AdditiveMilpPolicy(models, opt_rain, seed=seed)),
        _RecordingPolicy(NetworkAwarePolicy(models, opt_rain, seed=seed)),
    ]
    outcomes = {w.name: step.run(w, world, scen, models) for w in policy_list}
    plans = {w.name: (w.plan or {}) for w in policy_list}

    rows = []
    for name in POLICY_ORDER:
        out = outcomes[name]
        spend = out.spend
        per_crore = metrics.access_lost_per_crore(out.person_days.sum(), spend.sum())
        rows.append(
            {
                "policy": name,
                "mean_person_days": float(out.person_days.mean()),
                "sd_person_days": float(out.person_days.std()),
                "mean_planned_crore": float(out.planned.mean()),
                "mean_emergency_crore": float(out.emergency.mean()),
                "mean_spend_crore": float(spend.mean()),
                "person_days_per_crore": float(per_crore) if np.isfinite(per_crore) else None,
                "cvar_person_days": float(cvar(out.person_days, 0.1)),
                "plan": plans[name],
            }
        )

    comparison = None
    if "worst_first" in outcomes and "network_aware" in outcomes:
        ci = stats.paired_bootstrap_ci(
            outcomes["worst_first"].person_days,
            outcomes["network_aware"].person_days,
            rng=seed,
        )
        comparison = {
            "metric": "person-days lost, worst_first - network_aware (positive = network-aware better)",
            "mean": float(ci.mean),
            "ci_lo": float(ci.lo),
            "ci_hi": float(ci.hi),
            "n_scenarios": int(scen.n),
        }

    return {
        "ok": True,
        "params": p,
        "district_id": district_id_for(p),
        "district": summarize(district_id_for(p), seed),
        "n_assets": n_assets,
        "budget_crore": p["budget_crore"],
        "years": p["years"],
        "policies": rows,
        "comparison": comparison,
        "register": live.describe(),
        "map": _map_payload(district, world, models),
    }


def consequence(district_id: str, failed, seed: int = 0, live=None) -> dict:
    """Set-based accessibility loss ``L(F)`` for a chosen failure set on a district."""
    spec = get_spec(district_id)
    live = live if live is not None else live_register()
    district, models, world = build_world_models(
        district_id, seed, stress_conditions=False, live=live
    )
    node_of = {aid: a.node for aid, a in world.assets.items()}
    failed = [str(f) for f in (failed or [])]
    for f in failed:
        if f not in node_of:
            raise ValueError(f"unknown structure {f!r}")

    solo = {aid: float(models.acc.loss(failed_nodes=[n])) for aid, n in node_of.items()}
    set_loss = (
        float(models.acc.loss(failed_nodes=[node_of[f] for f in failed])) if failed else 0.0
    )
    corridor_of = {}
    if spec.redundancy:
        corridor_of = {
            aid: int(aid.lstrip("S")) // spec.redundancy for aid in node_of
        }
    return {
        "ok": True,
        "district_id": district_id,
        "redundancy": spec.redundancy,
        "seed": seed,
        "failed": failed,
        "set_loss": set_loss,
        "sum_solo": float(sum(solo[f] for f in failed)),
        "solo": solo,
        "corridor_of": corridor_of,
        "map": _map_payload(district, world, models),
    }


def run_loss(body: dict) -> dict:
    """Legacy ``/api/loss`` entry point: failure set on the redundant testbed."""
    body = body or {}
    redundancy = _clamp("redundancy", body.get("redundancy", 2), 1, 4, cast=int)
    seed = _clamp("seed", body.get("seed", 0), 0, 999, cast=int)
    failed = [str(s) for s in body.get("failed", [])][:12]
    district_id = f"synth-redundant-r{redundancy}"
    live = live_register()
    key = "loss:" + json.dumps(
        {"d": district_id, "seed": seed, "f": sorted(failed), "r": live.fingerprint}
    )
    with _RUN_LOCK:
        if key in _CACHE:
            return _CACHE[key]
        out = consequence(district_id, failed, seed=seed, live=live)
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = out
        return out
