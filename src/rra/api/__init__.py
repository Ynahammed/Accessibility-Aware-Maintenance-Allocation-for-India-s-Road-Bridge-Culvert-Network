"""FastAPI application for the accessibility-aware maintenance planner.

Routes are thin: they validate input, call the application services in ``rra.app`` and
map domain errors to HTTP status codes. The deployment entry point is ``app`` (also
re-exported by the repository-root ``app.py`` for Vercel).

Endpoint groups
---------------
* discovery  - ``/api/health``, ``/api/districts``, ``/api/districts/{id}``,
               ``/api/districts/{id}/assets``, ``/api/assumptions``
* planning   - ``/api/districts/{id}/plan``, ``/api/districts/{id}/simulate``,
               ``/api/districts/{id}/consequence``
* legacy lab - ``/api/run``, ``/api/loss``, ``/api/evidence`` (kept for the local
               stdlib demo server and existing clients)
* UI         - ``/`` serves ``demo/index.html``
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from rra.app import (
    build_plan,
    consequence,
    get_evidence,
    list_districts,
    network_view,
    run_experiment,
    run_loss,
)
from rra.app.districts import assets_payload, get_spec, summarize
from rra.app.register import assumptions_payload, live_register
from rra.app.lab import POLICY_ORDER

from .schemas import (
    ConsequenceRequest,
    LossRequest,
    PlanRequest,
    RunRequest,
    SimulateRequest,
)

__version__ = "0.2.0"
UI_PATH = Path(__file__).resolve().parents[3] / "demo" / "index.html"
_DESCRIPTION = (
    "Accessibility-aware maintenance allocation for a road-bridge-culvert network. "
    "Allocation results are simulator-only on synthetic districts; provenance is "
    "reported with every payload."
)


def _call(fn):
    """Run a service call, mapping domain errors to HTTP responses."""
    try:
        return fn()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_app() -> FastAPI:
    app = FastAPI(title="Accessibility-Aware Maintenance Allocation", version=__version__,
                  description=_DESCRIPTION)

    @app.middleware("http")
    async def _no_store(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # -- UI ------------------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def index():
        if not UI_PATH.exists():  # pragma: no cover - packaging guard
            raise HTTPException(status_code=500, detail="demo/index.html is missing")
        return file_response(UI_PATH)

    # -- discovery -----------------------------------------------------------------
    @app.get("/api/health", tags=["discovery"])
    def health() -> dict:
        return {
            "ok": True,
            "version": __version__,
            "n_districts": len(list_districts()),
            "policies": list(POLICY_ORDER),
        }

    @app.get("/api/districts", tags=["discovery"])
    def districts(seed: int = 0) -> dict:
        return {"ok": True, "districts": list_districts(seed)}

    @app.get("/api/districts/{district_id}", tags=["discovery"])
    def district(district_id: str, seed: int = 0) -> dict:
        return _call(lambda: {"ok": True, "district": summarize(district_id, seed)})

    @app.get("/api/districts/{district_id}/assets", tags=["discovery"])
    def district_assets(district_id: str, seed: int = 0) -> dict:
        return _call(lambda: assets_payload(district_id, seed))

    @app.get("/api/districts/{district_id}/network", tags=["discovery"])
    def district_network(district_id: str, seed: int = 0) -> dict:
        return _call(lambda: network_view(district_id, seed))

    @app.get("/api/assumptions", tags=["discovery"])
    def assumptions() -> dict:
        # One payload builder for both transports (see rra.serve) so they cannot drift.
        return assumptions_payload()

    @app.get("/api/evidence", tags=["discovery"])
    def evidence() -> dict:
        return get_evidence()

    # -- planning ------------------------------------------------------------------
    @app.post("/api/districts/{district_id}/plan", tags=["planning"])
    def district_plan(district_id: str, request: PlanRequest | None = None) -> dict:
        req = request or PlanRequest()
        spec = _call(lambda: get_spec(district_id))
        return _call(
            lambda: build_plan(
                spec.id,
                budget_crore=req.budget_crore,
                crew_days=req.crew_days,
                seed=req.seed,
                scenarios=req.scenarios,
                years=req.years,
            )
        )

    @app.post("/api/districts/{district_id}/consequence", tags=["planning"])
    def district_consequence(district_id: str, request: ConsequenceRequest | None = None) -> dict:
        req = request or ConsequenceRequest()
        return _call(lambda: consequence(district_id, req.failed, seed=req.seed))

    @app.post("/api/districts/{district_id}/simulate", tags=["planning"])
    def district_simulate(district_id: str, request: SimulateRequest | None = None) -> dict:
        req = request or SimulateRequest()
        spec = _call(lambda: get_spec(district_id))
        if spec.status != "ready":
            raise HTTPException(
                status_code=400,
                detail=f"district {spec.id!r} has no allocation layer ({spec.status}); "
                       "only the road network and structure tags are available",
            )
        body = {
            "preset": spec.preset,
            "redundancy": spec.redundancy or 2,
            "stress": req.stress,
            "seed": req.seed,
            "scenarios": req.scenarios,
            "years": req.years,
        }
        if req.budget_crore is not None:
            body["budget_crore"] = req.budget_crore
        return _call(lambda: run_experiment(body))

    # -- legacy lab ----------------------------------------------------------------
    @app.post("/api/run", tags=["lab"])
    def lab_run(request: RunRequest | None = None) -> dict:
        return run_experiment((request or RunRequest()).model_dump())

    @app.post("/api/loss", tags=["lab"])
    def lab_loss(request: LossRequest | None = None) -> dict:
        return _call(lambda: run_loss((request or LossRequest()).model_dump()))

    return app


def file_response(path: Path):
    """Small indirection so the UI route needs no response import at module scope."""
    from fastapi.responses import FileResponse

    return FileResponse(path, media_type="text/html")


app = create_app()
