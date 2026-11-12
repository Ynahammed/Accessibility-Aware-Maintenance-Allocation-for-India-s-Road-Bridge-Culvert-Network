# Alappuzha network resilience — measured on the real district graph

This replaces the synthetic redundant-corridor testbed with measurements on the real
Alappuzha road graph: which mapped water crossings actually carry a habitation's route
to a hospital, whether losses on the same corridor add up, and what happens to access
when modelled flood depth closes roads.

**Crossings are unverified geometric road/water intersections.** A blocked edge models a
failed crossing, not an observed closure, a bridge condition, or a repair cost.

## Dry baseline (free-flow)

- 1,978 PMGSY habitations (2,165,691 people in the source population field).
- 309 mapped hospitals as destinations.
- Median travel time to a hospital: 2.4 min.
- Within 15 / 30 / 60 min: 99.2% / 99.3% / 99.3%.
- Unreachable: 14,508 people.

Accessibility has almost no variance in the dry baseline, which is itself a finding: in
Alappuzha the binding constraint is not routine distance to a mapped hospital.

## Do crossings actually carry the routes?

- 3,859 crossing candidates map to 3,331 distinct graph edges
  (median snap offset 0 m).
- Only 804 of those edges lie on any habitation's shortest path to a hospital.
- 1,041,085 people (48.1%) rely on at least
  one candidate crossing for their route to a hospital.

## Solo criticality

- Edges evaluated: 804.
- With any population-hours lost when that single crossing is closed: 730.
- Cutting hospital access entirely for some population: 74.

| Edge | Dependent origins | Population hours lost | Lose 30-min access | Cut off entirely |
|---|---|---|---|---|
| 6222–17656 | 7 | 798.4 | 0 | 0 |
| 8113–8114 | 11 | 724.0 | 0 | 0 |
| 8114–8115 | 11 | 724.0 | 0 | 0 |
| 51828–51829 | 14 | 720.5 | 0 | 0 |
| 67599–67600 | 4 | 607.8 | 0 | 0 |
| 78326–78327 | 7 | 436.1 | 0 | 0 |
| 65265–65271 | 3 | 418.8 | 0 | 0 |
| 16525–65277 | 3 | 418.8 | 0 | 0 |
| 16553–16554 | 3 | 418.8 | 0 | 0 |
| 37313–67596 | 3 | 368.0 | 0 | 0 |

## Non-additivity on real corridors

Corridors are groups of critical crossings on the same OSM way. For each, the joint loss
of closing them together is compared with the sum of their solo losses.

- Corridors evaluated: 56 (of 56 with two or more critical crossings).
- Joint loss exceeds the additive sum in 3 corridors.
- Total joint population-hours: 3,270.1 vs additive 6,860.0.

The largest gap is on way 389842056.0 with 2 critical crossings:
**19.6 population-hours** that no per-crossing sum can see (joint 111.5 vs additive 91.9).

## Access under modelled flood closure

Every graph edge whose midpoint falls in KSDMA modelled depth is closed, then hospital
access is recomputed. Two thresholds: any modelled water (0.1 cm) and ≥30 cm.

`population_hours_lost` counts only origins that stay connected; origins cut off
entirely are reported separately, so the two columns must be read together.

| Scenario | Depth | Blocked km | Lose 30-min access | Cut off entirely | Share cut off | Delayed only (hours) |
|---|---|---|---|---|---|---|
| historical 10yr | ≥0.1 cm | 1,665 | 581,076 | 581,076 | 26.8% | 4,323 |
| historical 10yr | ≥30 cm | 1,636 | 576,433 | 576,433 | 26.6% | 4,238 |
| historical 100yr | ≥0.1 cm | 2,083 | 742,199 | 742,199 | 34.3% | 5,407 |
| historical 100yr | ≥30 cm | 1,955 | 668,183 | 668,183 | 30.9% | 5,793 |
| rcp85 100yr | ≥0.1 cm | 3,061 | 1,043,011 | 1,043,011 | 48.2% | 6,423 |
| rcp85 100yr | ≥30 cm | 2,897 | 992,520 | 992,520 | 45.8% | 6,628 |

## What this does and does not establish

**1. Accessibility is not the dry-season constraint.** Routine hospital access is near
uniform: over 99% of population within 15 minutes. A maintenance rule justified by routine
distance would have almost nothing to allocate against in this district.

**2. Individual crossings do matter — via isolation, not delay.** About 48% of the
population relies on at least one mapped candidate crossing for its route to a hospital,
and 74 single-edge closures cut some
population off entirely. This is the empirical case for treating crossings as critical
assets, and it does not depend on any synthetic construction.

**3. Super-additivity is the exception on the real network, not the rule.** Of
56 corridors with two or more route-carrying crossings, only
3 show joint loss above the sum of solo losses.
In aggregate the joint loss is **3,270 hours against
6,860 additive** — i.e. *sub*-additive, because the
same origins are affected twice and share the same detours. The testbed that produced the
multiplicative effect was built with N parallel routes and one structure on each, which is
close to the opposite of this network's structure. **The network-aware objective therefore
earns its advantage only where that redundancy pattern exists**, which is what the E4
factorial hinted at and this measurement now pins down on real geography.

**4. Under modelled flooding, isolation dominates delay.** Closing edges in KSDMA modelled
depth cuts off whole communities rather than merely lengthening trips, which is the effect a
road-bridge-culvert maintenance rule is actually meant to prevent.

It does not establish that any crossing is deficient, that a closure would occur, or that
repairing one asset is worth its cost. There is still no Indian condition, inspection or
cost record in the project, and simultaneous closure of every flooded edge is a severe
scenario rather than an observed flood response.

Per-crossing and per-corridor tables are in this directory; aggregates are in `summary.json`.
