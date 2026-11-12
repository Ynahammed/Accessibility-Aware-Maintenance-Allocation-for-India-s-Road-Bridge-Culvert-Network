# Accessibility-Aware Maintenance Allocation

Prioritising road, bridge and culvert maintenance by the effect failures have on people's
access to health facilities and schools — and comparing that with the condition-first
ranking agencies actually use.

**Live dashboard:** <https://a1ccessibility.vercel.app/>

> **Research status.** This is a research prototype, not a production planning tool, and
> its allocation results are **not** recommendations for a real Indian district.
> **The project works on Indian data only.** Official Indian sources are in use for
> Alappuzha: Census 2011 village totals, PMGSY GeoSadak habitations and the PMGSY DRRP
> rural road network, the district OSM clip, and KSDMA return-period flood-depth rasters.
> Indian asset-condition and maintenance-cost inputs are still unavailable (see *Data
> availability*), so allocation experiments remain seeded-synthetic with the assumptions
> recorded in the register and varied in E8.
>
> The earlier US FHWA National Bridge Inventory (NBI) deterioration experiment (E1) is
> **archived and out of scope**: it is not Indian asset data and no NBI-trained result is
> presented as Indian evidence.

## What is in here

| Layer | What it does |
|---|---|
| `src/rra/` | Research core: network build, accessibility-loss consequence, hazard, deterioration, fragility/cost, simulator, optimiser, evaluation |
| `src/rra/app/` | Application services: district registry, paired lab, year-1 planner, evidence loader |
| `src/rra/api/` | FastAPI app (typed endpoints, `/docs`) serving the dashboard |
| `src/rra/serve.py` | Dependency-free local server with the same routes |
| `demo/` | Single-page dashboard (vanilla JS + SVG, no build step) |
| `experiments/` | Seeded E3, E4, E8 scripts, configs and frozen results (E1 is archived US work) |
| `tests/` | Unit, property and API tests (139 passing) |

The product question is answered end to end: **given a district, a budget and crew
capacity, which structures should be repaired this year, and what does the plan buy?**
Every number in the dashboard is computed live by the same code the experiments use.

## Quick start

Python 3.11+ (verified on 3.12). From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### Option A — dependency-free demo server

```bash
rra-demo --port 8737
# or: python demo/server.py --port 8737
```

Open <http://127.0.0.1:8737/>. No ASGI server or build step is needed.

### Option B — FastAPI app

```bash
pip install -e ".[server]"
rra-api --port 8000
```

Open <http://127.0.0.1:8000/> for the dashboard and
<http://127.0.0.1:8000/docs> for the interactive API schema. Both servers implement the
same routes; the FastAPI app is the deployment target.

### Tests

```bash
python -m pytest        # 139 tests
```

## The dashboard

1. **Live allocation lab** — budget, monsoon stress, seed and redundancy sliders re-run a
   paired five-policy experiment on shared scenario draws (common random numbers). The map
   shows the selected policy's year-1 plan; the table reports absolute loss, planned and
   emergency spend, CVaR, and a paired bootstrap verdict.
2. **District maintenance plan** — the product view: pick a district and a budget and get
   the network-aware year-1 recommendation, one row per structure, with the condition
   change, the fragility cut, cost, crew-days and a reason. Budget and crew are hard
   constraints.
3. **Non-additivity explorer** — fail structures on parallel routes and compare the true
   joint loss `L(F)` with the sum of solo losses. Solo losses are zero until a corridor
   loses every route, which is exactly what an additive model cannot see.
4. **Evidence** — KSDMA flood exposure on mapped Indian roads, frozen E3/E4/E8 results,
   measured data availability, OSM QA and the 21-parameter assumptions register.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Version, district count, policy names |
| `GET` | `/api/districts` | Study districts with provenance and status |
| `GET` | `/api/districts/{id}` | One district |
| `GET` | `/api/districts/{id}/assets` | Structure state, outage, solo loss |
| `POST` | `/api/districts/{id}/plan` | Budget-constrained year-1 recommendation |
| `POST` | `/api/districts/{id}/simulate` | Paired five-policy comparison |
| `POST` | `/api/districts/{id}/consequence` | Set-based loss for a failure set |
| `GET` | `/api/assumptions` | The assumptions register in force |
| `GET` | `/api/evidence` | Frozen experiment results and data availability |
| `POST` | `/api/run`, `/api/loss` | Legacy lab endpoints (kept for the demo page) |

Full request/response reference: [`docs/api.md`](docs/api.md).

```bash
curl -s http://127.0.0.1:8000/api/districts | python -m json.tool
curl -s -X POST http://127.0.0.1:8000/api/districts/synth-redundant-r3/plan \
  -H 'Content-Type: application/json' \
  -d '{"budget_crore": 0.4, "scenarios": 8}' | python -m json.tool
```

## How a PWD/RTI reply reaches live planning

The register a plan uses is not only the one in `src/rra/assumptions.py`: once a reply is
ingested, its measured rows replace the assumed ones for every request until the override
file is removed.

1. **Put the reply in a folder** holding the tables and `manifest.json` described by
   [`docs/rti/reply_template/`](docs/rti/reply_template/README.md).
2. **Run the loader.** It validates the reply, derives what the sample supports, and writes
   the override file (default `--out` is `data/processed/pwd_reply`):

   ```bash
   python scripts/ingest_pwd_reply.py data/raw/pwd/rti_2026_11 --write-docs
   ```

   - `data/processed/pwd_reply/register_overrides.json` — each override with its
     provenance (`real` when the reply states the value, `fitted` when it is computed from
     the reply's rows), plus every row left alone with the reason it was refused;
   - `coverage.json` — what the reply covered and what it did not;
   - `condition_transitions.csv` — exported for later fitting, not applied;
   - with `--write-docs`, `docs/assumptions_measured.md`.

   A reply that lacks provenance, has too small a sample, uses an unmapped type or quotes
   an implausible rate keeps that row assumed and records the refusal; it never invents a
   value. Rates that look like rupees or lakh rather than crore are refused, not rescaled.
3. **The app reads that file at request time.** `src/rra/app/register.py` is the only reader
   of `register_overrides.json`, and planning, simulation and evidence all resolve the live
   register, so re-running the loader takes effect without a restart (the file is re-read
   when its modification time or size changes).
4. **Measured values widen the sweep range.** An override becomes the parameter's point
   value and pushes its sweep bounds outward; it is never clipped to the registered range.
   For example `outage_mean_days_culvert` moves from 3–30 (assumed 10) to 3–44.5 (measured
   44.5), so E8 draws still cover the measured value instead of excluding it.
5. **Provenance travels with the numbers.** A plan payload's `provenance.register` is the
   same `LiveRegister.describe()` object that `/api/assumptions` returns as `source` and
   the evidence payload returns as `assumptions_source`: source (`default` or `pwd_rti`),
   office, application reference, reply date, the applied parameters and priced structure
   types, a register fingerprint, and counts of refused overrides and coverage warnings.
   The dashboard prints that line under every plan with a `measured` or `assumed` pill, and
   lists the refused rows with their reasons in the assumptions panel.
6. **Removing the file returns the defaults.** With no `register_overrides.json` the next
   request uses the default register and the placeholder schedule of rates again — no
   restart, cache purge or code change needed.

## What the evidence says

Evidence is tagged by provenance; the distinctions matter when reading it.

| Input or result | Current evidence |
|---|---|
| Bridge/culvert condition and deterioration | **No Indian condition data.** No public asset-level PWD/IBMS inspection or condition register was found for Alappuzha; a PWD data request is required — the drafted application, with every requested field mapped to the register entry it would replace, is in [`docs/rti/alappuzha_structure_data_request.md`](docs/rti/alappuzha_structure_data_request.md). The archived US NBI experiment is not used as Indian evidence. |
| Road graph | District-wide Geofabrik/OSM extract clipped to the 2011 Alappuzha polygon: 30,434 road ways; routable graph has 290,041 nodes and 299,430 undirected edges (single largest weak component contains 98.8% of nodes); 2,318 bridge-tagged edges and no culvert-tagged edges. Older town-area graph is retained separately. Road/water intersections yield 3,859 point-level screening candidates (linear waterways, drainage, and waterbody shorelines), all explicitly unverified. A separate graph-edge QA counts 8,177 road edges intersecting mapped water geometries; these are different screening measures, neither a verified structure count. See `data/raw/osm_alappuzha_district/README.md` and `data/processed/alappuzha_network_join/README.md`. |
| Settlements and population | **Two universes, reconciled — not a conflict.** The Census 2011 village PCA is the **rural** subtotal: 52 villages, 979,643 residents. The district total is 2,127,789 (rural 979,643 + urban 1,148,146); urban wards are not village rows. The PMGSY habitation field totals 2,169,418, i.e. **1.020× the district total** and 2.21× the rural subtotal, so it is a district-wide habitation layer, not duplication. The weak link is the name crosswalk: only 28 of 1,981 PMGSY points matched a village row, so village-level reweighting is not defensible. See `data/processed/alappuzha_population_reconcile/`. 1,978 PMGSY points have connectors within 500 m; 22 matched Census villages are connected, 30 keep null coordinates (541,961 rural residents, 25.5% of the district). Never add the two totals. |
| Facilities and asset condition/cost | The district OSM clip contains 425 mapped health facilities and 1,000 mapped schools/colleges/kindergartens; these are volunteered OSM points, not an authoritative complete facility register. The 1,425 OSM facility points are attached to the network within 500 m. PWD asset-level bridge/culvert condition and maintenance-cost records remain unavailable. Public PWD sanctions/tenders are project estimates, not inspection ratings or realized maintenance costs; see [`data/processed/alappuzha_pwd_public_records.md`](data/processed/alappuzha_pwd_public_records.md). No validated real-network allocation loss can yet be computed. |
| PMGSY rural road network | Official PMGSY DRRP layer (Nov 2021/DRRP 2022 release, Government Open Data Licence): 1,839 Alappuzha links, 2,297 km measured in UTM 43N, with road category, name and owner. It carries no condition, traffic, inspection or cost attribute, and it is a district plan rather than an audited as-built register. |
| Flood exposure | All 12 official KSDMA return-period layers (10/25/50/100/200/500 yr, historical and RCP8.5) are decoded and overlapped with mapped roads, facilities and habitations: `data/processed/alappuzha_flood_exposure/`. Results are **modelled hazard overlap**, not observed flooding. |
| Settlement access | Nearest-mapped-facility travel times from PMGSY habitations and located Census villages on the district OSM graph: `data/processed/alappuzha_access_baseline/`. Free-flow class speeds only. |
| IMD rainfall | Not yet integrated as observed model inputs. |
| State PWD / IBMS condition | PRICE describes controlled asset registers and work histories, but no complete public asset-level export was found; requires a PWD request. Available Alappuzha Government Orders and eTender values are individually named construction/tender estimates only, not asset condition/cost history. See [`data/processed/alappuzha_pwd_public_records.md`](data/processed/alappuzha_pwd_public_records.md). |
| Allocation experiments (E3, E4, E8) | Seeded synthetic districts, synthetic scenarios and register parameters — simulator experiments, not observed district outcomes. |

### Indian evidence: what Alappuzha supports today

**Flood exposure (KSDMA, modelled).** Overlapping the official return-period depth rasters
with the PMGSY DRRP network: 20.4% of PMGSY length lies in modelled depth at the 10-year
historical layer and 39.2% at the RCP8.5 100-year layer; 20.1% and 37.3% respectively are at
or above an indicative 30 cm vehicle threshold. Modelled depth at 816 of 1,981 PMGSY
habitation points reaches 30 cm under RCP8.5 100-year, covering 882,478 of the 2,169,418
people in the PMGSY population field.

These are **modelled hazard overlap** numbers. KSDMA's state-wide hydraulic product keeps
water standing on drained kayal land — 35.5% of the district at the 10-year return period,
concentrated in the central paddy belt — so the absolute shares overstate expected
inundation. The layer is usable for *relative* exposure and for how the exposed set grows
under RCP8.5, not for expected closures, damage or repair cost.

**Access (OSM graph, free-flow).** 1,978 of 1,981 PMGSY habitation points attach to the
district graph within 500 m; 25 attached habitations (14,508 people in the PMGSY field) have
no route to any mapped hospital. Only 22 of 52 Census 2011 villages have a defensible
coordinate, so 541,961 of the 979,643 rural residents (25.5% of the district total) cannot be
placed at all and are reported as unlocated rather than assigned to an arbitrary point. The
PMGSY field 2,169,418 is 1.020× the district total, so the two sources agree at district scale;
they disagree only when the district-wide field is compared with the rural subtotal.

**Resilience measured on the real graph** (`data/processed/alappuzha_resilience/`, `scripts/alappuzha_resilience.py`).
This replaces the synthetic redundant-corridor testbed with measurement:

- 3,859 unverified crossing candidates map to 3,331 graph edges; **804** of those carry a
  habitation's shortest route to a hospital, and **48.1% of the population** (1,041,085 people)
  depends on at least one of them.
- Closing one such edge changes access for 730 of the 804; **74 cut some population off
  entirely**. Individual criticality is real and needs no constructed testbed.
- **Super-additivity is the exception.** Of 56 corridors with two or more route-carrying
  crossings, only 3 have joint loss above the sum of solo losses; in aggregate joint loss is
  **3,270 population-hours against 6,860 additive** — sub-additive, because the same origins
  are hit twice and share detours. The E4 testbed built N parallel routes with one structure
  each, which is close to the opposite of this network.
- Under modelled flood closure the dominant effect is **isolation, not delay**: at RCP8.5
  100-year with a 30 cm threshold, 2,897 km of road is cut and 992,520 people (45.8%) lose
  30-minute hospital access, essentially all of them by being cut off.

So the honest framing of the method's value is conditional: network-aware allocation pays only
where the redundancy structure exists, and on this district a per-crossing criticality ranking
is closer to the truth than a joint-loss objective.

### E1 — archived: deterioration on US NBI histories

This experiment ran on US FHWA National Bridge Inventory records and is **out of scope for
this India-only project**. It is retained for provenance only: the agency-style age-class
Markov baseline had a lower test log-loss than gradient boosting (0.1636 vs 0.1772), so the
"ML beats Markov" claim was not supported on that walk-forward split. **No NBI-trained
result is presented as Indian evidence, and it is no longer served by the dashboard or
`/api/evidence`.**

### E4 — do network effects matter?

Mean person-days lost on the redundant-corridor testbed (lower is better):

| Redundancy | do nothing | worst-first | benefit-cost | additive MILP | network-aware | additive − network |
|---|---|---|---|---|---|---|
| 1 | 26,005 | 15,824 | 21,467 | 7,237 | 7,237 | +0 |
| 2 | 15,579 | 5,643 | 15,579 | 15,579 | **2,821** | +12,757 |
| 3 | 10,304 | 4,907 | 10,304 | 10,304 | **3,557** | +6,747 |
| 4 | 8,709 | 2,821 | 8,709 | 8,709 | **2,453** | +6,256 |

At redundancy ≥ 2 every structure's solo loss is zero **by construction of the testbed**, so
the additive MILP does exactly nothing, while the network-aware objective cuts joint loss.
That is a demonstration, not a discovery: the corridor generator builds N parallel routes and
solo loss is then zero by algebra. The factorial below is the attempt to escape it, and it
does **not** support dominance over condition-first: significantly better in 5/24 redundant
cells, never significantly worse, and inconclusive in 19/24.

The honest claim is therefore conditional: **network-awareness pays only above a redundancy
threshold, and a naive benefit-cost rule matches or beats it in most assumption draws** (E8:
benefit-cost wins 62% of draws with lower mean regret). E3's set-based search is also 1.4%
*worse* in absolute loss than the additive MILP on an unredundant district. See
`data/processed/alappuzha_resilience/` for the same question measured on the real Alappuzha
graph instead of a testbed.

**Factorial check (36 cells).** Repeating the comparison on a series (chain) district and
sweeping budget (₹0.2/0.6 cr) and fragility slope (0.6/2.0) confirms the *additive*
threshold but weakens the condition-first claim: at r=1 the two optimisers agree in 8/8
cells, at r≥2 the additive gap is positive in 24/24 (significant in 22/24), and a first
gap appears at r=2 in 7/8 budget × slope settings — so the effect is not corridor-specific.
Against worst-first, network-aware is at or below it in only 16/24 cells and significantly
better in 5/24 (never significantly worse, 19 inconclusive); the r=4 win above (2,453 vs
2,821) does not survive the ₹0.6 cr budget in this grid (920 vs 690). The ablation is in
`experiments/e04_network_effects/factorial_results.md`.

### E3 — allocation comparison on a generic district

The optimisers beat condition-first (worst-first 17,776 person-days per ₹crore vs 11,761
for the additive MILP; paired difference +66,100, 95% CI [53,263, 79,654]). Additive and
network-aware remain close per rupee (11,761 vs 11,836), and the set-based search is 1.4%
above the additive MILP in absolute loss where a district has little redundancy — recorded
as an open issue.

### E8 — robustness across the assumptions register

`benefit_cost` wins 62% of eight assumption draws with the lowest mean regret; network-aware
wins 38% with mean regret 1,921 (additive MILP 2,085). The plan's headline claim that the
proposed method is near-best across the whole range is **not supported** on this district
as configured. The primary ratio metric rewards underspending, so absolute loss at equal
budget (E3/E4) is reported alongside it.

## Reproducing the experiments

Every number comes from a script + config + fixed seed; notebooks never produce results.

```bash
python experiments/e03_allocation/run.py      --config experiments/e03_allocation/config.json
python experiments/e04_network_effects/run.py --config experiments/e04_network_effects/config.json
python experiments/e04_network_effects/factorial.py   # topology x budget x slope + ablations
python experiments/e08_robustness/run.py      --config experiments/e08_robustness/config.json
python scripts/download_pmgsy_drrp.py         # PMGSY DRRP district road network (GodL)
python scripts/join_alappuzha_census.py       # Census village ↔ PMGSY habitation crosswalk
python scripts/attach_alappuzha_layers.py     # snap Census/PMGSY/OSM layers to the road graph
python scripts/alappuzha_access_baseline.py   # nearest-facility travel times
python scripts/alappuzha_flood_exposure.py    # KSDMA depth on roads, facilities, habitations
python scripts/alappuzha_resilience.py        # real crossing criticality, non-additivity, flood closure
python scripts/alappuzha_population_reconcile.py  # Census vs PMGSY denominators
```

Each experiment writes `results.json` and `results.md` next to itself; the dashboard reads
those files, so the evidence panel can never drift from the frozen results. The Alappuzha
join script writes a Census-village summary, a point-level crosswalk, and an unmatched
records report under `data/processed/`.

## Project layout

```text
src/rra/               Research core (network, consequence, hazard, deterioration,
                       fragility, cost, simulator, optimise, evaluate, assumptions)
src/rra/app/           Application services (districts, lab, planning, evidence)
src/rra/api/           FastAPI app and serving CLI
src/rra/serve.py       Stdlib demo server (same routes)
demo/                  Dashboard page
experiments/           Seeded E3/E4/E8 scripts, the E4 factorial, frozen results
                       (e01_deterioration is archived US work, out of scope)
data/raw/              Indian sources: district OSM, Census 2011, PMGSY habitation and
                       DRRP roads, KSDMA flood rasters (US NBI files are archived only)
data/processed/        Network QA reports and processed structure data
scripts/               Download, network QA and assumptions tools
docs/                  API reference and the assumptions register
tests/                 Unit, property and API tests
```

## Deployment

**Vercel:** import the repository with the project root at the repository root. Vercel
discovers `app.py`, which re-exports the FastAPI app; `requirements.txt` provides the
runtime dependencies. API routes are `GET /api/evidence`, `POST /api/run`,
`POST /api/loss` plus the district/plan endpoints in [`docs/api.md`](docs/api.md).
`.vercelignore` keeps raw datasets and local environments out of the upload.

**Docker:**

```bash
docker build -t rra .
docker run --rm -p 8000:8000 rra
```

**CI:** `.github/workflows/tests.yml` runs the suite on Python 3.11 and 3.12.

## Limitations and open issues

- No Indian asset-level bridge/culvert condition or maintenance-cost history, and no
  authoritative complete health/school destination layer. Public Alappuzha PWD project
  sanctions and tender estimates are not condition records or realized maintenance costs.
  A district-wide OSM extract is now available, but OSM bridge/water-crossing tags are
  incomplete and inferred crossings are only candidates; the graph is not yet joined to the
  partial Census/PMGSY population crosswalk or KSDMA flood rasters, so validated
  real-network allocation loss remains unavailable.
- The optimiser's sample-average surrogate is a rare-event estimator; a small fit sample
  can be driven to zero, which is why plans are selected on an independent validation
  sample. E3 still pays ~1.4% absolute loss for the wider search.
- The person-days-per-crore ratio rewards underspending; absolute loss at equal budget is
  always reported alongside it.
- `benefit_cost` remains hard to beat on the ratio metric (E8); the network advantage
  appears where the network is redundant (E4) — and only inside a budget/topology window:
  the factorial finds it significant in 5 of 24 redundant cells and never significantly
  negative, so it is a conditional result, not a dominance claim.
