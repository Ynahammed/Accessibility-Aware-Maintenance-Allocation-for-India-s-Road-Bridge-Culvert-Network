"""Live demo server — stdlib only, no new dependencies.

Serves ``demo/index.html`` and three JSON endpoints that call the **real** research
code in ``src/rra`` (the same functions the experiments and tests use):

    GET  /api/evidence   frozen experiment results (E1/E3/E4/E8), OSM QA, assumptions
    POST /api/run        paired allocation experiment on a synthetic district
                         (do_nothing / worst_first / benefit_cost / additive_milp /
                          network_aware on common random numbers)
    POST /api/loss       set-based accessibility loss for an arbitrary failure set
                         (the non-additivity explorer, redundant-corridor testbed)

Run::

    ./.venv/Scripts/python.exe demo/server.py --port 8737

Everything is seeded, so identical parameters return identical results (cached).
The demo is honest about provenance: allocation runs on a *synthetic* district
(IMD/PMGSY unreachable), deterioration evidence comes from *real* NBI data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from rra import pipeline  # noqa: E402
from rra.assumptions import AssumptionRegister  # noqa: E402
from rra.cost.interventions import Intervention  # noqa: E402
from rra.deterioration.markov import STATES  # noqa: E402
from rra.evaluate import metrics, stats  # noqa: E402
from rra.network.build import class_speeds_from_register  # noqa: E402
from rra.network.synthetic import make_district, make_redundant_district  # noqa: E402
from rra.optimize.cvar import cvar  # noqa: E402
from rra.simulator import policies, step  # noqa: E402
from rra.simulator.optimized_policies import (  # noqa: E402
    AdditiveMilpPolicy,
    NetworkAwarePolicy,
)

REGISTER = AssumptionRegister.default()

# one experiment at a time (the sim is CPU-bound; concurrent runs just thrash)
_RUN_LOCK = threading.Lock()
_CACHE: dict[str, dict] = {}
_CACHE_MAX = 64

POLICY_ORDER = (
    "do_nothing",
    "worst_first",
    "benefit_cost",
    "additive_milp",
    "network_aware",
)

DEFAULTS = {
    "preset": "generic",       # generic | redundant
    "budget_crore": 0.6,
    "stress": 0.0,             # mean log rainfall ratio (monsoon stress)
    "seed": 0,
    "scenarios": 8,
    "years": 3,
    "redundancy": 2,
}


class _RecordingPolicy:
    """Wraps a policy and captures its first-year plan for the map overlay."""

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.plan: dict | None = None

    def propose(self, assets, ctx):
        chosen = self.inner.propose(assets, ctx)
        if self.plan is None:
            self.plan = {aid: opt.value for aid, opt in chosen.items()}
        return chosen


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
    p["preset"] = body.get("preset") if body.get("preset") in ("generic", "redundant") else "generic"
    p["budget_crore"] = _clamp("budget_crore", body.get("budget_crore", p["budget_crore"]), 0.0, 5.0)
    p["stress"] = _clamp("stress", body.get("stress", p["stress"]), -1.0, 2.0)
    p["seed"] = _clamp("seed", body.get("seed", p["seed"]), 0, 999, cast=int)
    p["scenarios"] = _clamp("scenarios", body.get("scenarios", p["scenarios"]), 4, 32, cast=int)
    p["years"] = _clamp("years", body.get("years", p["years"]), 1, 5, cast=int)
    p["redundancy"] = _clamp("redundancy", body.get("redundancy", p["redundancy"]), 1, 4, cast=int)
    return p


def _map_payload(district, world, models) -> dict:
    """Serialise the graph + assets for the SVG renderer in the browser."""
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
    key = json.dumps(p, sort_keys=True)
    with _RUN_LOCK:
        if key in _CACHE:
            return _CACHE[key]
        t0 = time.time()
        out = _run_experiment(p)
        out["elapsed_seconds"] = round(time.time() - t0, 2)
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = out
        return out


def _run_experiment(p: dict) -> dict:
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
            class_speeds=class_speeds_from_register(REGISTER),
        )
        district.budget_crore = p["budget_crore"]
        district.crew_days = 1000.0
        sigma = 0.15

    models = pipeline.build_models(district, REGISTER, seed=seed)
    world = pipeline.build_world(district, REGISTER, seed=seed)
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
        "n_assets": n_assets,
        "budget_crore": p["budget_crore"],
        "years": p["years"],
        "policies": rows,
        "comparison": comparison,
        "map": _map_payload(district, world, models),
    }


def run_loss(body: dict) -> dict:
    """Set-based accessibility loss for a chosen failure set (explorer)."""
    body = body or {}
    redundancy = _clamp("redundancy", body.get("redundancy", 2), 1, 4, cast=int)
    seed = _clamp("seed", body.get("seed", 0), 0, 999, cast=int)
    failed = [str(s) for s in body.get("failed", [])][:12]

    key = "loss:" + json.dumps({"r": redundancy, "seed": seed, "f": sorted(failed)})
    with _RUN_LOCK:
        if key in _CACHE:
            return _CACHE[key]
        district = make_redundant_district(
            n_corridors=3,
            redundancy=redundancy,
            seed=seed,
            class_speeds=class_speeds_from_register(REGISTER),
        )
        models = pipeline.build_models(district, REGISTER, seed=seed)
        node_of = {aid: node for aid, node, _ in district.structures}
        for f in failed:
            if f not in node_of:
                raise ValueError(f"unknown structure {f!r}")
        solo = {aid: float(models.acc.loss(failed_nodes=[n])) for aid, n in node_of.items()}
        set_loss = float(models.acc.loss(failed_nodes=[node_of[f] for f in failed])) if failed else 0.0
        # corridor grouping: structures are created corridor-by-corridor in order
        corridor_of = {aid: int(re.match(r"S(\d+)", aid).group(1)) // redundancy for aid in node_of}
        out = {
            "ok": True,
            "redundancy": redundancy,
            "seed": seed,
            "failed": failed,
            "set_loss": set_loss,
            "sum_solo": float(sum(solo[f] for f in failed)),
            "solo": solo,
            "corridor_of": corridor_of,
            "map": _map_payload(district, _stub_world(district, seed), models),
        }
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = out
        return out


def _stub_world(district, seed):
    """World just for map payload (conditions/ages) in the explorer."""
    return pipeline.build_world(district, REGISTER, seed=seed)


def load_evidence() -> dict:
    """Frozen experiment results + QA + assumptions, read once at startup."""

    def read_json(rel):
        path = ROOT / rel
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def read_text(rel):
        path = ROOT / rel
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    e1 = read_json("experiments/e01_deterioration/results.json")
    e3 = read_json("experiments/e03_allocation/results.json")
    e4 = read_json("experiments/e04_network_effects/results.json")
    e8 = read_json("experiments/e08_robustness/results.json")

    data_matrix = [
        {"source": "US NBI (FHWA)", "status": "real",
         "note": "18 files, 233 MB; AL/CA/TX 2018-2023; 582k panel rows"},
        {"source": "OSM roads (Alappuzha)", "status": "real",
         "note": "1,972 nodes / 2,361 edges, 1 component; 3.13% bridge tags, 0% culvert"},
        {"source": "IMD rainfall (imdpune.gov.in)", "status": "blocked",
         "note": "TCP connect timeout from this environment (imdlib installed but unusable)"},
        {"source": "PMGSY GeoSadak", "status": "blocked", "note": "no route to host"},
        {"source": "State PWD / IBMS condition", "status": "unavailable",
         "note": "no public download; requires a data request"},
        {"source": "Allocation districts (E3/E4/E8)", "status": "synthetic",
         "note": "generated by network/synthetic.py — simulator-only numbers, no real-district claim"},
    ]

    return {
        "ok": True,
        "e1_deterioration": e1,
        "e3_allocation": e3,
        "e4_network_effects": e4,
        "e8_robustness": e8,
        "osm_qa": read_text("data/processed/osm_qa.md"),
        "real_district_qa": read_text("data/processed/real_district_qa.md"),
        "data_matrix": data_matrix,
        "assumptions": REGISTER.as_dict(),
        "register_markdown": read_text("docs/assumptions.md"),
    }


_EVIDENCE_CACHE: dict | None = None
_EVIDENCE_LOCK = threading.Lock()


def get_evidence() -> dict:
    global _EVIDENCE_CACHE
    with _EVIDENCE_LOCK:
        if _EVIDENCE_CACHE is None:
            _EVIDENCE_CACHE = load_evidence()
        return _EVIDENCE_CACHE


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "RRADemo/1.0"

    def log_message(self, fmt, *args):  # quiet but traceable
        sys.stderr.write("[demo] %s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers -------------------------------------------------------------------
    def _send_json(self, obj, status: int = 200) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, ctype: str) -> None:
        if not path.exists():
            self._send_json({"ok": False, "error": "not found"}, 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    # -- routes --------------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_file(Path(__file__).parent / "index.html", "text/html; charset=utf-8")
        elif path == "/api/evidence":
            self._send_json(get_evidence())
        else:
            self._send_json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        body = self._read_body()
        try:
            if path == "/api/run":
                self._send_json(run_experiment(body))
            elif path == "/api/loss":
                self._send_json(run_loss(body))
            else:
                self._send_json({"ok": False, "error": "not found"}, 404)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # never take the server down on a bad request
            import traceback

            traceback.print_exc()
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)


def main() -> None:
    ap = argparse.ArgumentParser(description="RRa live demo server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8737)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    print(f"demo server on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
