from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from demo.server import get_evidence, run_experiment, run_loss

app = FastAPI(title="Accessibility-Aware Maintenance Allocation Demo")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    demo_page = Path(__file__).resolve().parent / "demo" / "index.html"
    return FileResponse(demo_page, media_type="text/html")


@app.get("/api/evidence")
def evidence() -> dict:
    return get_evidence()


@app.post("/api/run")
def run(payload: dict | None = None) -> dict:
    return run_experiment(payload or {})


@app.post("/api/loss")
def loss(payload: dict | None = None) -> dict:
    try:
        return run_loss(payload or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
