"""Local, dependency-free demo server (stdlib only).

The research stack needs numpy/scipy/networkx, but serving the page does not need an
ASGI server: this module keeps the original one-command local demo working, while
delegating every computation to ``rra.app`` — the same services the FastAPI app uses.

    python demo/server.py --port 8737

Routes mirror the API (``docs/api.md``): the three legacy lab endpoints plus district
discovery, the year-1 plan, consequence queries and per-district simulation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
from rra.app.evidence import load_evidence  # noqa: F401  (public API)
from rra.app.register import assumptions_payload
from rra.app.lab import (  # noqa: F401  (public API)
    DEFAULTS,
    POLICY_ORDER,
    normalize_params,
)

PAGE = Path(__file__).resolve().parents[2] / "demo" / "index.html"

_ID = r"([^/]+)"
_ASSETS = re.compile(rf"^/api/districts/{_ID}/assets$")
_PLAN = re.compile(rf"^/api/districts/{_ID}/plan$")
_CONSEQ = re.compile(rf"^/api/districts/{_ID}/consequence$")
_SIM = re.compile(rf"^/api/districts/{_ID}/simulate$")
_NETWORK = re.compile(rf"^/api/districts/{_ID}/network$")
_DISTRICT = re.compile(rf"^/api/districts/{_ID}$")


class _DomainError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _guarded(fn):
    try:
        return fn()
    except KeyError as exc:
        raise _DomainError(404, str(exc).strip("'")) from exc
    except ValueError as exc:
        raise _DomainError(400, str(exc)) from exc


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "RRADemo/2.0"

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

    def _handle(self, method: str) -> None:
        path = self.path.split("?", 1)[0]
        # FastAPI accepts a trailing slash on a declared route; normalise it here so a
        # client that works against one transport does not get a 404 from the other.
        if len(path) > 1:
            path = path.rstrip("/") or "/"
        body = self._read_body() if method == "POST" else {}
        try:
            if method == "GET":
                if path in ("/", "/index.html"):
                    self._send_file(PAGE, "text/html; charset=utf-8")
                    return
                if path == "/api/health":
                    self._send_json(
                        {"ok": True, "version": "0.2.0", "n_districts": len(list_districts())}
                    )
                    return
                if path == "/api/districts":
                    self._send_json({"ok": True, "districts": list_districts()})
                    return
                if m := _ASSETS.match(path):
                    self._send_json(_guarded(lambda: assets_payload(m.group(1))))
                    return
                if m := _NETWORK.match(path):
                    self._send_json(_guarded(lambda: network_view(m.group(1))))
                    return
                if m := _DISTRICT.match(path):
                    self._send_json(
                        _guarded(lambda: {"ok": True, "district": summarize(m.group(1))})
                    )
                    return
                if path == "/api/assumptions":
                    # Same payload builder as the FastAPI route, so the transports agree.
                    self._send_json(assumptions_payload())
                    return
                if path == "/api/evidence":
                    self._send_json(get_evidence())
                    return
            else:
                if path == "/api/run":
                    self._send_json(run_experiment(body))
                    return
                if path == "/api/loss":
                    self._send_json(_guarded(lambda: run_loss(body)))
                    return
                if m := _PLAN.match(path):
                    self._send_json(
                        _guarded(
                            lambda: build_plan(
                                m.group(1),
                                budget_crore=body.get("budget_crore"),
                                crew_days=body.get("crew_days"),
                                seed=int(body.get("seed", 0)),
                                scenarios=int(body.get("scenarios", 8)),
                                years=int(body.get("years", 1)),
                            )
                        )
                    )
                    return
                if m := _CONSEQ.match(path):
                    self._send_json(
                        _guarded(
                            lambda: consequence(
                                m.group(1),
                                body.get("failed", []),
                                seed=int(body.get("seed", 0)),
                            )
                        )
                    )
                    return
                if m := _SIM.match(path):
                    spec = _guarded(lambda: get_spec(m.group(1)))
                    if spec.status != "ready":
                        raise _DomainError(
                            400,
                            f"district {spec.id!r} has no allocation layer ({spec.status})",
                        )
                    sim_body = {
                        "preset": spec.preset,
                        "redundancy": spec.redundancy or 2,
                        "stress": body.get("stress", 0.0),
                        "seed": body.get("seed", 0),
                        "scenarios": body.get("scenarios", 8),
                        "years": body.get("years", 3),
                    }
                    if body.get("budget_crore") is not None:
                        sim_body["budget_crore"] = body["budget_crore"]
                    self._send_json(run_experiment(sim_body))
                    return
            self._send_json({"ok": False, "error": "not found"}, 404)
        except _DomainError as exc:
            self._send_json({"ok": False, "error": exc.detail}, exc.status)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # never take the server down on a bad request
            import traceback

            traceback.print_exc()
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_GET(self):  # noqa: N802
        self._handle("GET")

    def do_POST(self):  # noqa: N802
        self._handle("POST")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the local interactive demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8737)
    args = parser.parse_args(argv)

    httpd = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    print(f"demo server on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        httpd.server_close()


if __name__ == "__main__":
    main()
