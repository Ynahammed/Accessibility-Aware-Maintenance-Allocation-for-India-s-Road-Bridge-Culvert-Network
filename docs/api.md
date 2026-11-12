# HTTP API

The FastAPI app (`rra.api:app`) serves the dashboard at `/` and a JSON API under `/api`.
The local stdlib server (`python demo/server.py`) implements the same routes, so the page
behaves identically whether you run `rra-api` or the dependency-free demo server.

All responses are JSON and set `Cache-Control: no-store`. Every allocation payload carries
provenance: districts are **seeded synthetic** testbeds, and costs/fragility are register
assumptions that E8 varies.

## Error handling

| Status | Meaning |
|---|---|
| `400` | Domain error: unknown structure, or a district with no allocation layer |
| `404` | Unknown district id |
| `422` | Request validation failed (field out of range, wrong type) |

Error bodies from the stdlib server are `{"ok": false, "error": "..."}`; FastAPI returns
`{"detail": "..."}`.

## Discovery

### `GET /api/health`
```json
{"ok": true, "version": "0.2.0", "n_districts": 5,
 "policies": ["do_nothing", "worst_first", "benefit_cost", "additive_milp", "network_aware"]}
```

### `GET /api/districts?seed=0`
Lists study districts with provenance, status and size. `status` is `ready` for the
synthetic allocation testbeds and `network-only` for the legacy Alappuzha town-area OSM
map. District-wide Census/PMGSY and OSM facility/crossing layers are documented separately
in `data/processed/alappuzha_network_join/`; they are not inputs to the allocation model,
and PWD condition/cost records remain unavailable.

### `GET /api/districts/{id}`
One district, same shape as a list entry.

### `GET /api/districts/{id}/assets?seed=0`
Per-structure state used by the asset table: type, condition (0 Good … 3 Severe), age,
`outage_days`, the accessibility loss of failing it alone (`solo_loss`), and the corridor
index on the redundant testbeds.

### `GET /api/districts/{id}/network?seed=0`
Read-only network geometry for the map: `nodes` (`id`, `x`, `y`) and `edges`
(`u`, `v`, `bridge`, `culvert`, `length_m`), plus `counts` and `read_only`. The
`alappuzha-osm` endpoint returns the legacy town-area view: 1,972 nodes, 2,361 edges and
74 bridge-tagged edges from `data/raw/osm/roads.graphml`, parsed with networkx alone so
the base install can serve it. It is not the district-wide Alappuzha graph.

It contains **no** condition, age, cost, loss, spend or recommendation fields. District-wide
Census/PMGSY and OSM facilities/crossing candidates are maintained as separate evidence;
PWD asset-level condition and maintenance costs remain unavailable, so validated district
allocation results cannot be computed. If the town-area OSM extract is missing (for example
a deployment that excludes `data/raw/`), the endpoint returns `400` naming the download
script.

### `GET /api/assumptions`
The 21-parameter assumptions register (`parameters`, plus `register_markdown` rendered from the
**live** register and `source`, the provenance block). Served identically by the FastAPI app and
the stdlib demo server (`demo/server.py`) from one payload builder, `rra.app.register.assumptions_payload`. When a validated PWD/RTI reply has been
ingested, the rendered table carries the measured values and names the application it came from;
the generated `docs/assumptions.md` is the default register and is not served here.

### `GET /api/evidence`
Indian evidence only: the Alappuzha KSDMA flood-exposure and network-access summaries, the
frozen synthetic allocation results (E3/E4/E8), OSM and real-district QA text, the measured
data-availability matrix and the assumptions register. US National Bridge Inventory results
are archived and deliberately absent from this payload.

The register fields (`assumptions`, `assumption_overrides`, `assumptions_source`,
`register_markdown`) are re-resolved on every request from the loader output, so the rendered
markdown always matches the values the planner and simulator use.

## Planning

### `POST /api/districts/{id}/plan`
Budget-constrained year-1 recommendation from the network-aware optimizer.

```json
{"budget_crore": 0.4, "crew_days": 1000, "seed": 0, "scenarios": 8, "years": 1}
```

`budget_crore`/`crew_days` default to the district's registered values. The response
contains one row per structure (funded or not), with the option, cost, labour, condition
before/after, the fragility multiplier bought by the repair, and a human-readable reason:

```json
{
  "ok": true,
  "district": {"id": "synth-redundant-r3", "provenance": "synthetic", "...": "..."},
  "budget_crore": 0.4,
  "n_funded": 3,
  "planned_spend_crore": 0.4,
  "crew_days_used": 75.0,
  "recommendations": [
    {"id": "S4", "type": "culvert", "state": "Poor", "recommended": "major",
     "cost_crore": 0.08, "labour_days": 20.0, "condition_after": 0,
     "state_after": "Good", "fragility_factor": 0.5, "solo_loss": 0.0,
     "funded": true, "reason": "major repair resets condition Poor -> Good and ..."}
  ],
  "loss": {
    "mean_person_days": {"do_nothing": 52629.0, "worst_first": 37639.0,
                         "additive_milp": 35210.0, "network_aware": 31206.0},
    "paired_worst_first_minus_network_aware":
      {"mean": 6432.0, "ci_lo": 1296.0, "ci_hi": 14392.0, "n_scenarios": 8}
  },
  "provenance": {"district": "synthetic", "costs": "assumed (placeholder ...)", "note": "..."}
}
```

The plan is validated against the budget and crew constraint before it is returned.

### `POST /api/districts/{id}/simulate`
Runs the five-policy paired comparison on the district (shared scenarios, common random
numbers). Body: `{budget_crore?, stress, seed, scenarios, years}`. Returns policy rows,
planned/emergency/total spend, CVaR, the paired bootstrap comparison against worst-first,
and the map payload used by the UI.

### `POST /api/districts/{id}/consequence`
Set-based accessibility loss `L(F)` for a failure set:
`{"failed": ["S0", "S1"], "seed": 0}`. Returns `set_loss`, `sum_solo`, per-structure
`solo`, corridor grouping and the map. This is the non-additivity explorer's data source:
on a redundant testbed each structure's solo loss is zero but the joint loss is not.

## Legacy lab endpoints

Kept for the original demo page and existing clients; they are thin wrappers over the
same services.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/evidence` | Frozen results (same as above) |
| `POST` | `/api/run` | Paired experiment by `preset` (`generic`/`redundant`) |
| `POST` | `/api/loss` | Set loss on the redundant testbed by `redundancy` |

## Running

```bash
pip install -e ".[server]"   # adds uvicorn
rra-api --port 8000          # FastAPI + dashboard
rra-demo --port 8737         # stdlib server, no ASGI dependency
```

Interactive schema: <http://127.0.0.1:8000/docs>.
