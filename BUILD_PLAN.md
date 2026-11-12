# Build Plan — Accessibility-Aware Maintenance Allocation

> Derived from the 24-week research plan. **Weeks are ignored here on purpose.** They are
> replaced by an ordered set of *work packages* (WP) in dependency order. Each WP states
> its inputs, its deliverable, and the concrete check that proves it is done. Work the
> WPs top-to-bottom; never start a WP whose inputs are not yet green.

The plan's own "never cut" list fixes the priority spine:
**network-aware consequence · paired evaluation · assumptions register · honest baselines.**

---

## 0. Guiding rules (from the plan, restated as build constraints)

- Every result comes from a **script + config + fixed seed**, never a notebook.
- **Common random numbers**: all policies see the same scenario draws; differences are paired.
- Every component is validated against **real or hand-built ground truth**, never against
  the simulator's own output.
- Every number in the paper is tagged: `real` | `fitted` | `assumed`.
- Cut order (last never cut): narration → extra dashboard views → second district →
  survival model M2 → rolling horizon → *never* consequence/paired-eval/assumptions/baselines.

---

## Work packages

### WP0 — Assumptions register (living artifact)  `[no dependencies]`
- **Input:** literature-derived ranges for fragility betas, deterioration acceleration,
  repair effectiveness, outage durations, facility weights, travel-time caps, speeds.
- **Deliverable:** `src/rra/assumptions.py` + `docs/assumptions.md`; a register object that
  can (a) emit defaults, (b) sample a parameter set with a seed, (c) render its own Markdown,
  (d) declare each entry's range/source.
- **Check:** sampling is seed-reproducible; Markdown round-trips; every parameter has a range
  and a source tag. **This gates every sweep, so it comes first.**

### WP1 — Network model + build  `[needs WP0 for speeds/snap tolerance]`
- **Input:** node/edge tables (later: PMGSY + OSM; now: synthetic fixtures).
- **Deliverable:** `network/build.py` (routable graph with `length_m`, `road_class`,
  `speed_kph`, `travel_time_s`), `network/snap.py` (nearest-node attach within a cap + log
  of overshoots), `network/attach_assets.py` (structures, edge splits), `qa_report`.
- **Check:** QA report gives connected components, % habitations connected, orphan
  facilities, tag coverage. Exit test: >95% of habitations reach ≥1 health facility on the
  intact network, else district rejected.

### WP2 — Accessibility-loss consequence (the contribution)  `[needs WP1]`
- **Input:** network + habitations (population) + facilities by type + policy caps `T_k` and
  weights `w_k`.
- **Deliverable:** `consequence/accessibility.py` computing
  `L(F)=Σ_h Σ_k P_h w_k [φ(τ_k^F(h)) − φ(τ_k^0(h))]`, `φ(τ)=min(τ/T_k,1)`,
  unreachable = cap; multi-source Dijkstra from facilities on the reversed graph; non-additive
  set evaluation.
- **Check (toy graphs, exact hand answers):**
  1. single bridge on the *only* route → loss = cut-off population (× w_k × Δφ);
  2. two parallel routes → 0 individually, **>0 jointly** (non-additivity);
  3. `L(∅)=0`, non-negative, **monotone** as assets are added to F.

### WP3 — Rainfall hazard  `[needs WP0]`
- **Input:** IMD gridded daily rainfall (imdlib) — or synthetic for tests.
- **Deliverable:** `hazard/gev_fit.py` (per-cell GEV via `scipy.stats.genextreme`, pooled
  where records are short, GOF + QQ), `hazard/scenarios.py` (years resampled as spatial
  fields; stress events scaled to a return level).
- **Check:** return levels strictly increase with period; fitted tails finite; scenario
  fields preserve cross-cell correlation.

### WP4 — Deterioration  `[needs WP0]`
- **Input:** no Indian inspection histories exist yet; synthetic fixtures only (the archived
  US NBI panel is out of scope and must not be used as Indian evidence).
- **Deliverable:** `deterioration/markov.py` (M0 age-class Markov + bootstrap rows),
  `gbm.py` (M1), `survival.py` (M2), `conformal.py` (split-conformal on time-to-Poor).
- **Check:** split by **inspection year** (train early / validate mid / test latest);
  log-loss, RPS, concordance, calibration, conformal coverage by group. M0 must be honest,
  not strawman.

### WP5 — Fragility, outage, cost  `[needs WP0, WP4 states]`
- **Input:** assumption ranges + condition states + PWD Schedule of Rates.
- **Deliverable:** `fragility/fragility.py` (`σ(β0+β1·g(c)+β2·log(R/R_ref))` per type),
  `cost/sor.py`, `cost/interventions.py` (none/minor/major/replace with cost, labour,
  condition+fragility effect, emergency premium).
- **Check:** monotone in condition and rainfall ratio; costs non-negative; premium sweeps.

### WP6 — Policy simulator (paired harness)  `[needs WP2/W4/W5]`
- **Input:** network, forecasts, fragility, costs, hazard scenarios.
- **Deliverable:** `simulator/state.py`, `simulator/step.py` (one simulated year),
  `simulator/policies.py` (do-nothing, random, worst-first, benefit-cost, criticality,
  siloed, additive-MILP, network-aware, network-aware+CVaR+rolling).
- **Check:** same random draws reused across policies (paired); per-policy distributions of
  person-days lost and ₹ spent + CVaR; components validated separately, never by the sim.

### WP7 — Optimizer  `[needs WP6]`
- **Input:** paired failure indicators under common random numbers.
- **Deliverable:** `optimize/milp.py` (additive LP/MILP: budget, crew-days, one option per
  asset; CVaR via `η,z`), `local_search.py` (swap moves on sample-average set loss),
  `cvar.py`, `rolling.py`.
- **Check (property tests):** more budget never raises optimal loss; zero budget ≡ do-nothing;
  reproducible under fixed seed; on small instances report gap vs a linearized exact solve
  (no optimality guarantee claimed for the full non-additive problem).

### WP8 — Evaluation protocol  `[needs WP6/WP7]`
- **Input:** policy outputs on shared scenarios.
- **Deliverable:** `evaluate/metrics.py` (person-days lost per ₹ crore, 5-yr horizon),
  `stats.py` (paired bootstrap CIs, resample scenarios/regions, ≥5 seeds → medians+ranges),
  `regret.py` (win-rate + regret over the register), `ablation.py` (drop one component).
- **Check:** primary metric paired across policies; pre-registered cost/weight settings;
  tune on one scenario set, report on a fresh one.

### WP9 — Experiments E1–E8 (results freeze before write-up)  `[needs WP8]`
- E1 ML vs Markov · E2 conformal coverage · E3 access vs condition · E4 network effects ·
  E5 unified vs siloed · E6 uncertainty · E7 re-planning · E8 robustness/ablation.
- **Check:** every result regenerates from a config file.

### WP10 — Product layer (only after results freeze)  `[needs WP9]`
- Orchestrator DAG (pure functions, MLflow-logged) → FastAPI → React+MapLibre dashboard.
- LLM narration with a **number-matching check** against the result JSON. Human approves.
- **Check:** 30–50 test requests → correct plan; numeric-faithfulness share; one-command repro.

---

## Gate decisions (from the plan's risks)

| Gate | Trigger | Decision |
|---|---|---|
| Data fallback | no IBMS/PWD reply by ~3 WP2-completions | frame as methodology; assumption-swept deterioration (no foreign-data validation) + honest provenance tags |
| OSM tag sparsity | structure coverage low vs expected density early | infer crossings where roads meet water, or use PMGSY structures |
| District QA fail | <95% habitations reach a health facility | reject district, try the other candidate |
| Simulator circularity | component not independently validated | block the result until validated |

---

## Status tracker

| WP | Status |
|----|--------|
| WP0 Assumptions register | **done** (21 params, 8 tests) |
| WP1 Network model | **done** (build/snap/attach/QA, 13 tests) |
| WP2 Accessibility consequence | **done** (set-based L(F) + brute-force cross-check, 14 tests) |
| WP3 Hazard | **done** (GEV fit/pooling/return levels + scenarios, 7 tests) |
| WP4 Deterioration | **done** (M0 Markov+age classes, M1 GBM, M2 survival, conformal, 13 tests) |
| WP5 Fragility/cost | **done** (logistic fragility, SoR, interventions, 8 tests) |
| WP6 Simulator | **done** (state/step/policies, CRN paired harness, planned vs emergency spend, 5 tests) |
| WP7 Optimizer | **done** (additive MILP+CVaR, network-aware search with pair moves / restarts / out-of-sample selection, instance builders, 12 tests) |
| WP8 Evaluation | **done** (log-loss/RPS/concordance, paired bootstrap, regret; ablation pending) |
| WP9 Experiments | **E3 + E4 + E8 done**; E2/E5/E6/E7 pending. E1 (US NBI) archived and out of scope |
| Data | **Indian only.** District-wide Alappuzha OSM, Census 2011, PMGSY habitations and PMGSY DRRP roads downloaded and spatially joined; all 12 KSDMA flood-depth layers overlapped with roads and points; access baseline computed. IMD rainfall and PWD condition/cost records remain unavailable |
| WP10 Product | **done for this scope** — installable package (`pyproject.toml`, `rra-demo`/`rra-api` scripts), shared service layer (`rra.app`), typed FastAPI API (`rra.api`, 13 tests) reusing the stdlib server, dashboard with year-1 plan sign-off view and a read-only real-OSM network viewer (4 sections), Docker/CI/docs. React/MapLibre frontend not used: vanilla JS + SVG, no build step |

### Live demo (`demo/`)

Two transports over the same service layer, no build step:

```
rra-demo --port 8737     # stdlib server (base install), http://127.0.0.1:8737/
rra-api  --port 8000     # FastAPI app, http://127.0.0.1:8000/ (+ /docs)
```

Four sections, all backed by the **same `src/rra` code the experiments use**:

1. **Live allocation lab** — budget / monsoon-stress / seed / redundancy sliders re-run a
   paired 5-policy experiment (~0.2–1.4 s, server-cached); district map with year-1 plan
   overlay, person-days chart, paired bootstrap CI verdict, full policy table with planned
   vs emergency spend. Honest by construction: when worst-first wins (symmetric redundant
   district), the UI says so in red — that's the E4 local-search open issue, surfaced not hidden.
2. **Non-additivity explorer** — click structures on the redundant testbed; shows `L(F)` vs
   `Σ solo losses` live (corridor cut: 368 vs 0). The one-minute version of the whole thesis.
3. **District maintenance plan** — pick a district and a budget; the network-aware optimizer returns a
   year-1 sign-off table (structure, intervention, cost, crew-days, condition after, failure-odds
   multiplier, reason) with plan vs worst-first vs do-nothing loss and a paired bootstrap CI.
4. **Evidence** — KSDMA flood exposure on mapped Indian roads, E3/E4/E8 frozen results,
   measured data-availability matrix, OSM/real-district QA, and the assumptions register.

Tests: `tests/test_demo.py` (9 tests — clamping, paired results, caching, non-additivity,
unknown-structure rejection, evidence shape) and `tests/test_api.py` (13 tests — REST contract, request
validation, error mapping, the plan endpoint, both transports). Full suite: **132 passing**.

### Results log

> **Data status (India-only).** The active evidence base is Indian: OSM, Census 2011,
> PMGSY habitation points, the PMGSY DRRP road network and all 12 KSDMA flood-depth layers.
> E3/E4/E8 remain **synthetic districts** because Indian asset-condition and maintenance-cost
> records are unavailable, so allocation results are simulator-only — no real-district or
> ₹/lives claim. **E1 is archived**: it was fitted to US FHWA National Bridge Inventory
> records, which are out of scope for this project and no longer served as evidence.

> **Units corrected.** All costs are now ₹ crore (`cost/sor.py`); earlier figures mixed
> lakh and crore. The numbers below supersede everything before this line.

> **Simulator fix (E3/E4/E8 re-run on 2026-11-07).** Planned interventions now carry their
> direct fragility effect in the simulator, as plan 5.5 specifies and as the optimizer's
> instance builder already assumed. Before this, a repair only reset condition, so the
> optimizer over-paid for replacements that bought no extra protection in the simulated
> world. E1 is unaffected.

> **Optimizer search fix (E3/E4/E8 re-run again, same day).** Network-aware local search
> now uses two-asset swap moves (so it can free budget on one asset to fund a better
> repair elsewhere), seeded random-but-feasible restarts, and picks among candidate plans
> on an independent validation sample — the sample-average surrogate is a rare-event
> estimator, so a small fit sample can be driven to exactly zero. Set losses are memoised,
> which is what makes the wider search affordable. E4 shows the effect: condition-first is
> now behind at every redundancy. E3's unredundant district pays ~1.4% absolute loss for
> it, recorded below. E1 is unaffected.

#### E1 — ARCHIVED: US NBI, out of scope for this project

E1 was fitted to US FHWA National Bridge Inventory records (AL/CA/TX, 2018–2023) and is
retained for provenance only. **It is not Indian evidence and is no longer served by the
dashboard or `/api/evidence`.** No Indian asset-level condition or inspection register is
available, so deterioration cannot be validated on Indian structures; WP4's models remain
implementation + synthetic tests, and any deterioration claim in an allocation result stays
tagged `assumed`.

<details><summary>Archived numbers, for provenance only — do not cite as Indian evidence</summary>

| Model | Log-loss | RPS | Accuracy |
|---|---|---|---|
| M0 age-class Markov (agency baseline) | **0.1636** | **0.0353** | **0.965** |
| M1 gradient boosting | 0.1772 | 0.0366 | 0.964 |
| climatology | 0.8107 | 0.2792 | 0.471 |

Train years ≤ 2020, test years ≥ 2022. The agency-style Markov baseline beat the GBM, so the
plan's "deterioration forecasts beat Markov baselines" claim was not supported on that split.

</details>

#### E3 — allocation comparison (14 habitations, 10 structures, 40 scenarios × 5 yr, ₹0.6 cr/yr)

| Policy | mean person-days | mean spend (₹cr) | person-days per crore | CVaR |
|---|---|---|---|---|
| additive_milp | 131,816 | 11.21 | **11,761** | 234,136 |
| network_aware (proposed) | 133,638 | 11.29 | 11,836 | 247,713 |
| random | 208,552 | 12.32 | 16,935 | 317,286 |
| benefit_cost | 208,552 | 12.32 | 16,935 | 317,286 |
| worst_first | 199,738 | 11.24 | 17,776 | 320,300 |
| criticality_weighted | 199,738 | 11.24 | 17,776 | 320,300 |
| siloed | 240,898 | 11.57 | 20,817 | 370,383 |
| do_nothing | 257,792 | 12.06 | 21,373 | 398,512 |

Paired (same scenarios): worst_first − network_aware = **+66,100 person-days**, 95% CI
[53,263, 79,654].

Reading: both optimizers clearly beat the condition-based and random baselines (**H1
directionally supported vs condition ranking**), and additive MILP and network-aware remain
close per rupee (~11.8k each). In absolute mean loss the set-based search now sits 1.4%
*above* the additive MILP here (133,638 vs 131,816): a generic district has little
redundancy for the network term to exploit, so wider search buys in-sample rare-event fit
rather than out-of-sample protection. Reported, not hidden.

#### E8 — robustness/regret (8 assumption draws, synthetic district)

| Policy | Win rate | Mean regret | Max regret |
|---|---|---|---|
| benefit_cost | 0.62 | **169.27** | **556.35** |
| network_aware (proposed) | 0.38 | 1,920.81 | 9,403.66 |
| additive_milp | 0.00 | 2,084.56 | 5,877.79 |
| do_nothing | 0.00 | 22,076.92 | 49,138.06 |
| worst_first | 0.00 | 25,798.80 | 53,840.86 |

**Reading (honest):** benefit_cost wins 62% of assumption sets and has by far the lowest
regret. Network-aware now wins 38% (was 12%) with mean regret 1,921, i.e. ahead of the
additive MILP on mean regret but still behind benefit-cost, so the plan's headline claim
(H2 — the proposed method is near-best *across the whole range*) is **NOT supported** on
this district as currently configured. Two causes, recorded rather than hidden:

1. The primary metric (**person-days per ₹crore**) rewards *underspending*: benefit-cost
   spreads cheap minor repairs, spends least, and so scores well by ratio even with higher
   absolute loss. The plan's E4/E5 measure — **absolute loss at equal budget** — is the
   fairer comparison and must accompany it.
2. The proposers' edge should appear where consequences are non-additive; see E4 next.

#### E4 — do network effects matter? (redundant corridors, monsoon stress, ₹0.4 cr/yr)

| Redundancy | do nothing | worst-first | benefit-cost | additive MILP | network-aware | additive − network |
|---|---|---|---|---|---|---|
| 1 | 26,005 | 15,824 | 21,467 | 7,237 | 7,237 | +0 |
| 2 | 15,579 | 5,643 | 15,579 | 15,579 | 2,821 | +12,757 |
| 3 | 10,304 | 4,907 | 10,304 | 10,304 | 3,557 | +6,747 |
| 4 | 8,709 | 2,821 | 8,709 | 8,709 | 2,453 | +6,256 |

Reading:

1. **The testbed shows what it was built to show.** At redundancy ≥ 2 every structure's solo
   loss is zero *by construction* — the corridor generator places N parallel routes with one
   structure on each — so the additive MILP does exactly nothing (= do-nothing: 15,579,
   10,304, 8,709) while the network-aware objective finds reductions of 12,757, 6,747 and
   6,256 person-days. At redundancy 1 the two agree. **This is a demonstration of algebra, not
   a discovery**, and it must not be reported as evidence that real networks behave this way.
   The real-network measurement is in `scripts/alappuzha_resilience.py`, which computes solo
   versus joint crossing loss on the Alappuzha graph with its actual detours.
2. Condition-first is ahead nowhere in this testbed: network-aware is at or below worst-first
   at every redundancy (7,237 vs 15,824; 2,821 vs 5,643; 3,557 vs 4,907; 2,453 vs 2,821).
   The earlier gap — the plan's flagged "local search gives poor solutions" risk — came from
   a budget-binding single-move search. Two-asset swap moves, seeded restarts and
   out-of-sample candidate selection closed it (see the results-log note).
3. Absolute loss falls as redundancy grows, so the additive − network gap peaks at
   *moderate* redundancy rather than at high r.

> **Factorial follow-up (2026-11-07).** `experiments/e04_network_effects/factorial.py` repeats the
> comparison over 36 cells: families {corridors, chain} x redundancy 1-4 x budget Rs 0.2/0.6 crore x
> fragility slope 0.6/2.0, plus a mesh reference and search ablations. At r=1 the additive and
> network-aware plans agree in 8/8 cells; at r>=2 the additive gap is positive in 24/24 (95% CI
> significant in 22/24), and a first positive gap appears at r=2 in 7/8 family x budget x slope
> settings. **The threshold is therefore not a property of the corridor generator.** But the
> advantage over **condition-first** is not general: the network plan is at or below worst-first in
> 16/24 cells, significantly better in only 5/24, never significantly worse, and inconclusive in
> 19/24. In particular E4's fixed-setting r=4 win (2,453 vs 2,821) does not survive a budget change
> to Rs 0.6 crore, where the same cell gives 920 vs 690. Ablations: pair moves matter at r=4
> (3,450 single-move vs 2,070 full), restarts matter at r=2-3, and out-of-sample selection never
> changed the chosen plan at these sample sizes. Read these as a **characterisation of when
> network-awareness pays**, not as a dominance claim.

#### Real-network measurement (2026-11-09) — replaces the E4 testbed as evidence

`scripts/alappuzha_resilience.py` measures the same question on the Alappuzha graph instead of
a constructed testbed:

| Quantity | Result |
|---|---|
| Crossing candidates on a habitation's hospital route | 804 of 3,331 edges |
| Population relying on at least one such crossing | 1,041,085 (48.1%) |
| Single closures that change access | 730 of 804 |
| Single closures that cut population off entirely | 74 |
| Corridors (≥2 route-carrying crossings) | 56 |
| Corridors where joint loss exceeds the additive sum | **3** |
| Joint vs additive population-hours | **3,270 vs 6,860 (sub-additive)** |
| RCP8.5 100-yr, ≥30 cm closure: population losing 30-min access | 992,520 (45.8%), essentially all by isolation |

**This corrects the E4 narrative.** The testbed showed a large joint-vs-additive gap because it
builds N parallel routes with one structure on each, making solo loss zero by construction. On
the real network the aggregate effect runs the other way: joint loss is roughly half the
additive sum, because the same habitations are affected twice and use the same detours. The
network-aware objective is therefore conditional on a redundancy structure that this district
largely lacks; a per-crossing criticality ranking matches the real structure more closely.

### Data availability (measured, not assumed)

| Source | Status from this environment |
|---|---|
| **OSM** (Geofabrik Southern Zone extract) | **real, Indian, downloaded** — district-wide Alappuzha clip; original town-area files retained separately |
| **Census 2011** (ORGI village PCA) | **real, Indian, downloaded** — 52 rural village rows, 979,643 residents (the rural subtotal; district total 2,127,789 includes 1,148,146 urban); 22 have a defensible coordinate, 30 remain unlocated. Reconciled against the PMGSY field in `data/processed/alappuzha_population_reconcile/` |
| PMGSY GeoSadak habitations | **real, Indian, downloaded** — 1,981 in-boundary points, snapped separately to the district road graph |
| PMGSY DRRP rural roads | **real, Indian, downloaded** — 1,839 Alappuzha links, 2,297 km; road category, name and owner; no condition/traffic/cost attributes. Government Open Data Licence |
| KSDMA flood depth | **real, Indian, downloaded** — 12 return-period layers (10–500 yr, historical and RCP8.5), ~92 m cells, modelled depth in cm; overlapped with mapped roads and points |
| IMD rainfall (`imdpune.gov.in`) | **blocked** — TCP connect timeout, even with imdlib installed |
| State PWD / IBMS condition | no public download; needs a request. No Indian condition data exists in the project |
| US NBI (FHWA) | **archived only** — outside the India-only scope; 18 files retained on disk for provenance, served by nothing |

**OSM tag coverage measured** on the district graph: 2,318 bridge-tagged edges and
**0 culvert-tagged edges**. A point-level screen of road/water intersections identifies
3,859 candidates across waterways, drains, and waterbody shorelines. A separate QA counts
8,177 graph edges intersecting mapped water geometries; the methods/counting units differ.
Neither measure verifies bridges or culverts. OSM is volunteered mapping, not an
authoritative PWD asset register or complete facility inventory.

### Real-data build status

Repeatable district-wide OSM clipping is implemented in `scripts/clip_alappuzha_osm.py`;
settlement, facility, and provisional crossing layers are joined in
`scripts/attach_alappuzha_layers.py`. The district graph has 290,041 nodes, 299,430
undirected edges, and a 98.8% largest weak component. The older town-area graph remains
available separately.

- Structure tags: 2,318 bridge-tagged edges, **0 tagged culverts**. The point-level screen
  retains 3,859 unverified crossing candidates; separate graph-edge QA reports 8,177
  road edges intersecting mapped water. These are different screens, not asset counts.
- District clip includes 168 OSM places and 1,425 health/school facilities. OSM remains
  volunteered mapping, not an authoritative facilities or PWD asset register.
- The Census/PMGSY crosswalk matches 22/52 village rows; 30 villages retain null
  coordinates. PMGSY and Census populations are stored separately. See
  `data/processed/alappuzha_census2011_pmgsy_join.md` and
  `data/processed/alappuzha_network_join/README.md`.

**Observed asset-condition allocation loss over a real district cannot be computed yet**:
PWD condition and maintenance-cost records remain unavailable, the Census/PMGSY crosswalk
is partial, and OSM facilities/crossing candidates are provisional. The population,
facility, and crossing layers are now connected to the district graph as documented in
`data/processed/alappuzha_network_join/README.md`. The consequence half remains open.

### Open issues surfaced (do not paper over)

- **Metric:** report absolute loss at equal budget alongside person-days-per-crore.
- **Local search:** factorial follow-up supersedes the old single-grid condition-first
  claim. Pair moves matter at r=4 and restarts at r=2–3; across the grid, network-aware is
  significantly better than worst-first in 5/24 redundant cells, never significantly
  worse, with 19 inconclusive. See `experiments/e04_network_effects/factorial_results.md`.
- **Residual E3 gap:** on the unredundant district the set-based search is 1.4% above the
  additive MILP in absolute mean loss (133,638 vs 131,816). Wider search on a rare-event
  surrogate buys in-sample fit where the network term has nothing to exploit.
- **Budget utilisation:** network-aware spends up to the annual cap while condition-first
  underspends, so every loss comparison must report spend alongside loss.
- **Budget utilisation:** policies may underspend; measure it explicitly.
