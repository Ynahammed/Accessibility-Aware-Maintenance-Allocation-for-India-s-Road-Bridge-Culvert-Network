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
- **Input:** NBI annual files (later), synthetic now.
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
| Data fallback | no IBMS/PWD reply by ~3 WP2-completions | frame as methodology; NBI-validated deterioration + assumption sweeps |
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
| WP7 Optimizer | **done** (additive MILP+CVaR, network-aware local search, instance builders, 12 tests) |
| WP8 Evaluation | **done** (log-loss/RPS/concordance, paired bootstrap, regret; ablation pending) |
| WP9 Experiments | **E1 (real NBI) + E3 + E4 + E8 done**; E2/E5/E6/E7 pending |
| Data | NBI **real** (18 files, 233 MB) + OSM **real** (Alappuzha bbox: 1,972 nodes / 2,361 edges) downloaded; IMD + PMGSY hosts unreachable here |
| WP10 Product | **live demo done** (`demo/server.py` + `demo/index.html`, stdlib-only, 9 tests) — full FastAPI/React layer still deferred |

### Live demo (`demo/`)

One command, no new dependencies, no build step:

```
./.venv/Scripts/python.exe demo/server.py --port 8737    # then open http://127.0.0.1:8737/
```

Three sections, all backed by the **same `src/rra` code the experiments use**:

1. **Live allocation lab** — budget / monsoon-stress / seed / redundancy sliders re-run a
   paired 5-policy experiment (~0.2–1.4 s, server-cached); district map with year-1 plan
   overlay, person-days chart, paired bootstrap CI verdict, full policy table with planned
   vs emergency spend. Honest by construction: when worst-first wins (symmetric redundant
   district), the UI says so in red — that's the E4 local-search open issue, surfaced not hidden.
2. **Non-additivity explorer** — click structures on the redundant testbed; shows `L(F)` vs
   `Σ solo losses` live (corridor cut: 368 vs 0). The one-minute version of the whole thesis.
3. **Evidence** — E1 (real NBI), E3, E4, E8 frozen results, measured data-availability matrix,
   OSM/real-district QA, and the 21-parameter assumptions register.

Tests: `tests/test_demo.py` (9 tests — clamping, paired results, caching, non-additivity,
unknown-structure rejection, evidence shape). Full suite: **113 passing**.

### Results log

> **Data status.** E1 uses **real NBI** bridge histories (FHWA — reachable from this
> environment). E3/E4/E8 use **synthetic districts**: the IMD (rainfall) and PMGSY
> (habitations) hosts were unreachable here, so there is no real Indian network or rainfall
> yet. Allocation results are simulator-only — no real-district or ₹/lives claim.

> **Units corrected.** All costs are now ₹ crore (`cost/sor.py`); earlier figures mixed
> lakh and crore. The numbers below supersede everything before this line.

#### E1 — deterioration on real NBI data (582k panel rows, 480k pairs, walk-forward split)

| Model | Log-loss | RPS | Accuracy |
|---|---|---|---|
| M0 age-class Markov (agency baseline) | **0.1636** | **0.0353** | **0.965** |
| M1 gradient boosting | 0.1772 | 0.0366 | 0.964 |
| climatology | 0.8107 | 0.2792 | 0.471 |

Train years ≤ 2020 (287k pairs), test years ≥ 2022 (97k pairs); states AL/CA/TX, 2018–2023.
Ingested by `src/rra/ingest/nbi.py`; run via `experiments/e01_deterioration/run.py`.

**Reading (honest):** condition states are strongly persistent, so the **agency-style Markov
baseline beats the GBM** — the plan's "deterioration forecasts beat Markov baselines" claim is
**NOT supported** on this split. M1 needs tuning (class weighting, more capacity, richer
features) before it can be claimed. Both models comfortably beat climatology (0.81 → 0.16),
so the deterioration pipeline is now **validated on real labelled histories**.

#### E3 — allocation comparison (14 habitations, 10 structures, 40 scenarios × 5 yr, ₹0.6 cr/yr)

| Policy | mean person-days | mean spend (₹cr) | person-days per crore | CVaR |
|---|---|---|---|---|
| additive_milp | 151,725 | 11.88 | **12,774** | 260,716 |
| network_aware (proposed) | 151,629 | 11.79 | 12,863 | 260,716 |
| random | 217,199 | 12.89 | 16,844 | 347,808 |
| benefit_cost | 217,199 | 12.89 | 16,844 | 347,808 |
| worst_first | 204,436 | 11.62 | 17,591 | 337,656 |
| criticality_weighted | 204,436 | 11.62 | 17,591 | 337,656 |
| siloed | 240,225 | 11.67 | 20,594 | 368,844 |
| do_nothing | 257,792 | 12.06 | 21,373 | 398,512 |

Paired (same scenarios): worst_first − network_aware = **+52,808 person-days**, 95% CI
[41,031, 64,768].

Reading: both optimizers clearly beat the condition-based and random baselines (**H1
directionally supported vs condition ranking**), but additive MILP and network-aware are
*effectively tied* on this district (~12.8k vs ~12.9k per crore) — as expected, since a
generic district has little redundancy for the network term to exploit.

#### E8 — robustness/regret (8 assumption draws, synthetic district)

| Policy | Win rate | Mean regret | Max regret |
|---|---|---|---|
| benefit_cost | 0.88 | **159.29** | **1,274.29** |
| network_aware (proposed) | 0.12 | 1,370.65 | 3,229.85 |
| additive_milp | 0.00 | 1,285.50 | 2,987.71 |
| do_nothing | 0.00 | 17,627.11 | 36,266.87 |
| worst_first | 0.00 | 20,188.04 | 37,890.10 |

**Reading (honest):** benefit_cost wins 88% of assumption sets and has by far the lowest
regret; the optimizers are mid-pack. So the plan's headline claim (H2 — the proposed method
is near-best *across the whole range*) is **NOT supported** on this district as currently
configured. Two causes, recorded rather than hidden:

1. The primary metric (**person-days per ₹crore**) rewards *underspending*: benefit-cost
   spreads cheap minor repairs, spends least, and so scores well by ratio even with higher
   absolute loss. The plan's E4/E5 measure — **absolute loss at equal budget** — is the
   fairer comparison and must accompany it.
2. The proposers' edge should appear where consequences are non-additive; see E4 next.

#### E4 — do network effects matter? (redundant corridors, monsoon stress, ₹0.4 cr/yr)

| Redundancy | do nothing | worst-first | benefit-cost | additive MILP | network-aware | additive − network |
|---|---|---|---|---|---|---|
| 1 | 26,005 | 19,381 | 24,901 | 19,381 | 19,381 | +0 |
| 2 | 15,579 | 8,709 | 15,579 | 15,579 | 10,795 | +4,784 |
| 3 | 10,304 | 6,501 | 10,304 | 10,304 | 7,851 | +2,453 |
| 4 | 8,709 | 4,293 | 8,709 | 8,709 | 6,133 | +2,576 |

Reading:

1. **Network effects matter.** At redundancy ≥ 2 every structure's solo loss is zero, so the
   additive MILP does *exactly nothing* (= do-nothing) while the network-aware objective
   finds real reductions. At redundancy 1 the two agree — additive already suffices when
   every structure is critical. **This is the E4 answer.**
2. But condition-first is strong on this symmetric district and currently edges out the
   network-aware search — consistent with the plan's own flagged risk ("local search gives
   poor solutions"; mitigation: seed from MILP, restart, better moves).
3. Absolute loss falls as redundancy grows, so the additive − network gap peaks at
   *moderate* redundancy rather than at high r.

### Data availability (measured, not assumed)

| Source | Status from this environment |
|---|---|
| US **NBI** (FHWA) | **real, downloaded** — 18 files, 233 MB (AL/CA/TX, 2018–2023) |
| **OSM** (Overpass via kumi mirror) | **real, downloaded** — Alappuzha bbox, fully connected (1 component) |
| IMD rainfall (`imdpune.gov.in`) | **blocked** — TCP connect timeout, even with imdlib installed |
| PMGSY GeoSadak (`geosadak-pmgsy.nic.in`) | **blocked** — no route |
| State PWD / IBMS condition | no public download; needs a request |

**OSM tag coverage measured** (`scripts/qa_osm_network.py`): 3.13% of edges tagged bridge,
**0.00% culvert** — the plan's "tags too sparse" risk is confirmed for culverts, so the
road↔water crossing inference (or PMGSY structures) is required before structure-based
allocation on real OSM data.

Overpass note: `overpass-api.de` returned 504/connect timeouts for district-sized queries
here; `overpass.kumi.systems` worked. The downloader now takes `--overpass-url` and
`--osm-bbox`.

### Real-data build status (`scripts/build_real_district.py`)

One command reconstructs the district network from raw OSM. On the Alappuzha bbox it
produces a fully connected graph (1,972 nodes / 2,361 edges) and reports the layers it
cannot yet complete, rather than pretending otherwise:

- structures: 74 tagged bridges, **0 tagged culverts** — crossing inference is built and
tested (`ingest/osm.py:infer_crossings`) but needs a water layer;
- habitations/facilities: 0 — needs the OSM place/amenity features or PMGSY.

**Accessibility loss over a real district cannot be computed yet** because both the
habitation and facility layers are unavailable: PMGSY is blocked here and Overpass feature
queries failed on every mirror. The road-geometry half of the plan's week-1 exit test is
met; the consequence half is blocked on data access, exactly the plan's top risk.

### Open issues surfaced (do not paper over)

- **Metric:** report absolute loss at equal budget alongside person-days-per-crore.
- **Local search:** needs restarts / better moves before network-aware can claim H1/H2.
- **Budget utilisation:** policies may underspend; measure it explicitly.
