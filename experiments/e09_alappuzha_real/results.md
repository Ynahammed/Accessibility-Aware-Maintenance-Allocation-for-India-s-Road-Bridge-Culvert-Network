# E9 — real Alappuzha network: allocation, inspection value, islanding

- instance: 1978 habitations, 30 structures, population 2165691
- structure mix: {'culvert': 30}
- habitations already beyond the 60-minute health cap before any failure: 25
- scenarios: 8, years: 2, budget Rs 0.5 cr, crew 150.0 days

## Policy panel (paired scenarios)

| Policy | Mean person-days | Spend (cr) | Person-days per crore | CVaR | Funded yr-1 |
|---|---|---|---|---|---|
| additive_milp | 44105.5 | 3.25 | 13570.9 | 59577.8 | 16 |
| benefit_cost | 55084.7 | 3.36 | 16404.0 | 68538.0 | 25 |
| random | 56348.8 | 3.34 | 16870.9 | 71742.2 | 25 |
| worst_first | 55254.1 | 3.14 | 17624.9 | 71727.3 | 13 |
| do_nothing | 73018.9 | 3.33 | 21927.6 | 90138.1 | 0 |

**Paired additive_milp - worst_first**: -11148.6 person-days, 95% CI [-15412.9, -6058.7] (positive = first is worse).

**Paired additive_milp - do_nothing**: -28913.4 person-days, 95% CI [-35267.5, -22485.0] (positive = first is worse).

**Comparators built, not assumed.** All 30 screened structures are culverts, so `siloed`'s per-class split is a no-op, and `criticality_weighted` ranks on a criticality proxy of 1 + condition, which orders assets similarly to condition but not identically once intervention costs differ. The three condition-based policies select the identical funded set at Rs 0.25 cr, Rs 0.5 cr, Rs 1 cr. They differ at Rs 0.1 cr: same count, different assets. The identity is therefore a property of this portfolio *and* budget, and only worst-first is reported at the panel's own budget.

Scenario win rate (share of scenarios where the policy loses fewest person-days): additive_milp 75%, worst_first 12%, random 12%, do_nothing 0%, benefit_cost 0%

## Condition-first practice against chance

| Metric | Condition-first | Random | Difference |
|---|---|---|---|
| Mean person-days lost | 55,254 | 56,349 | -1,095 |
| Mean spend, planned + emergency (Rs cr) | 3.14 | 3.34 | -0.21 |
| Person-days lost per crore | 17,625 | 16,871 | +754 |

Paired on the same 8 scenarios, condition-first minus random is -1,095 person-days (95% CI [-5,862, +4,108]); it loses fewer person-days in 75% of scenarios and more in 25%. The two metrics disagree in sign because random funds 25 cheaper structures and so spends more: condition-first is ahead in absolute loss, behind per crore. Either way the gap is 10% of the 11,149 person-days that accessibility-aware allocation recovers against the same baseline. On this network condition-first ranking performs close to chance, which is a stronger motivation for the method than the method's own win.

## Inspection value (which structure's condition is worth resolving)

| Structure | Type | Assumed | Plan gain | Plan changes in states |
|---|---|---|---|---|
| X005 | culvert | 1 | 907.4 | 2/3 |
| X004 | culvert | 1 | 906.4 | 2/3 |
| X003 | culvert | 1 | 892.7 | 1/3 |
| X011 | culvert | 1 | 781.9 | 1/3 |
| X017 | culvert | 1 | 552.6 | 1/3 |
| X019 | culvert | 1 | 522.7 | 1/3 |
| X018 | culvert | 1 | 452.5 | 1/3 |
| X023 | culvert | 1 | 414.8 | 1/3 |
| X022 | culvert | 1 | 397.7 | 1/3 |
| X025 | culvert | 1 | 361.5 | 1/3 |

Sum of positive gains: 6190.2 (base objective 22618.5).

## Single points of failure

0 of 30 structures cut any habitation off from a hospital when failing alone.

| Structure | Isolated habitations | Isolated population | Max extra one-way minutes |
|---|---|---|---|
| X001 | 0 | 0 | 4 |
| X002 | 0 | 0 | 7 |
| X003 | 0 | 0 | 7 |
| X004 | 0 | 0 | 5 |
| X005 | 0 | 0 | 5 |
| X006 | 0 | 0 | 4 |
| X007 | 0 | 0 | 7 |
| X008 | 0 | 0 | 7 |
| X009 | 0 | 0 | 7 |
| X010 | 0 | 0 | 2 |

## Benefit distribution

- habitations reached: 70 (4% of population)
- Gini of benefit per person: 0.490
- top 1% share of benefit: 0.00

## Destination sensitivity: hospitals against schools

Isolation depends on what counts as a destination. The audit above uses hospitals only — the most forgiving set in the district — so this repeats it with the school layer (schools, colleges, kindergartens) on the same 30 structures, the same graph and the same funded plan. No market layer exists to test: the OSM extract contains no `amenity=marketplace` points.

| Destination | Points | Cap (min) | Median access | Within cap | SPOF | Isolated population | Benefit Gini |
|---|---|---|---|---|---|---|---|
| health | 309 | 60 | 2.8 | 99.3% | 0 | 0 | 0.490 |
| school | 1,000 | 45 | 1.8 | 99.4% | 1 | 1,000 | 0.715 |

The school tier reuses the hospital-optimised funded plan, so its benefit split answers a distributional question about that plan rather than re-solving the optimiser for schools; the isolation counts are independent of the plan.

## Budget frontier (plan objective)

| Budget (cr) | Objective | Loss per crore | Funded |
|---|---|---|---|
| 0.10 | 33622.4 | 336223.8 | 5 |
| 0.25 | 28904.3 | 115617.3 | 12 |
| 0.50 | 22618.5 | 45236.9 | 16 |
| 1.00 | 16811.6 | 16811.6 | 15 |

## Robustness of the headline finding

### Equal planned spend

The panel above lets each rule spend what it chooses, so the absolute and per-crore readings can disagree in sign. Here every policy faces the same planned budget, including the budget at which condition-first actually spends at the reporting setting. Emergency restoration is reported but not equalised: it follows failure, it is not an allocation choice.

| Budget/yr (cr) | Policy | Mean person-days | Planned (cr) | Emergency (cr) | Funded |
|---|---|---|---|---|---|
| 0.250 | worst_first | 63,207 | 0.388 | 2.664 | 10 |
| 0.250 | random | 65,492 | 0.480 | 2.754 | 12 |
| 0.250 | benefit_cost | 61,964 | 0.480 | 2.862 | 12 |
| 0.250 | additive_milp | 64,052 | 0.480 | 2.898 | 12 |
| 0.398 | worst_first | 55,931 | 0.643 | 2.430 | 12 |
| 0.398 | random | 58,957 | 0.760 | 2.556 | 19 |
| 0.398 | benefit_cost | 56,668 | 0.760 | 2.520 | 19 |
| 0.398 | additive_milp | 49,937 | 0.760 | 2.592 | 13 |
| 0.500 | worst_first | 55,254 | 0.795 | 2.340 | 13 |
| 0.500 | random | 56,349 | 1.000 | 2.340 | 25 |
| 0.500 | benefit_cost | 55,085 | 1.000 | 2.358 | 25 |
| 0.500 | additive_milp | 44,106 | 1.000 | 2.250 | 16 |

Matched-spend comparison of condition-first against random:

| Budget/yr (cr) | WF planned | Random planned | Gap | Paired WF-random (95% CI) | WF better in |
|---|---|---|---|---|---|
| 0.250 | 0.388 | 0.480 | -0.093 | -2,285 (-5,241, +410) | 50% |
| 0.398 | 0.643 | 0.760 | -0.118 | -3,026 (-8,702, +2,672) | 50% |
| 0.500 | 0.795 | 1.000 | -0.205 | -1,095 (-5,862, +4,108) | 75% |

### Equivalence and precision

A confidence interval containing zero is not evidence of equivalence. The margin here is a share of what the additive policy recovers against condition-first, so the test asks whether practice is within a *policy-relevant* distance of chance.

| Scenarios | WF-random | SD | MDE | Additive gain | Margin | TOST p | Verdict | n required |
|---|---|---|---|---|---|---|---|---|
| 8 | -1,095 | 7,843 | 6,557 | 11,149 | 557 (5%) | 0.574 | inconclusive | 1224 |
| 8 | -1,095 | 7,843 | 6,557 | 11,149 | 1,115 (10%) | 0.497 | inconclusive | 306 |
| 40 | -4,096 | 7,633 | 2,441 | 3,549 | 177 (5%) | 0.999 | inconclusive | 11439 |
| 40 | -4,096 | 7,633 | 2,441 | 3,549 | 355 (10%) | 0.998 | inconclusive | 2860 |

An 'inconclusive' verdict means the design cannot demonstrate equivalence at that margin; `n required` is the paired scenario count a TOST at that margin would need at 80% power. The honest claim is therefore that practice is not distinguishable from chance and that the design is underpowered to claim more.

### Consequence-blind rules, not one baseline

| Rule | Mean person-days | Planned (cr) | Funded | Paired vs random (95% CI) | Better in |
|---|---|---|---|---|---|
| type_first | 62,382 | 1.000 | 3 | +6,033 (+268, +12,418) | 25% |
| road_class_first | 60,509 | 0.990 | 5 | +4,160 (-874, +9,398) | 38% |
| age_first | 60,878 | 0.992 | 5 | +4,529 (+120, +10,070) | 25% |
| random | 56,349 | 1.000 | 25 | - | - |
| worst_first | 55,254 | 0.795 | 13 | -1,095 (-5,862, +4,108) | 75% |
| cheapest_first | 55,254 | 0.795 | 13 | -1,095 (-5,862, +4,108) | 75% |
| do_nothing | 73,019 | 0.000 | 0 | - | - |

Every rule here buys the condition-appropriate intervention, so the comparison is about the ranking signal alone. None of them uses a consequence measure.

### Destination and travel-time cap, swept together

| Destination | Cap (min) | Points | Median access | Within cap | SPOF | Isolated people (summed) | Benefit Gini |
|---|---|---|---|---|---|---|---|
| health | 30 | 309 | 2.8 | 99.3% | 0 | 0 | 0.490 |
| health | 45 | 309 | 2.8 | 99.3% | 0 | 0 | 0.490 |
| health | 60 | 309 | 2.8 | 99.3% | 0 | 0 | 0.490 |
| health | 90 | 309 | 2.8 | 99.3% | 0 | 0 | 0.490 |
| school | 30 | 1,000 | 1.8 | 99.4% | 1 | 1,000 | 0.715 |
| school | 45 | 1,000 | 1.8 | 99.4% | 1 | 1,000 | 0.715 |
| school | 60 | 1,000 | 1.8 | 99.4% | 1 | 1,000 | 0.715 |
| school | 90 | 1,000 | 1.8 | 99.4% | 1 | 1,000 | 0.715 |

The hospital-at-60 cell is the most forgiving one in this table: sparsest destination set, loosest cap. Comparing cells separates the destination set from the cap, which a single hospital-versus-school pair cannot do.

### Does the selection rule drive the result?

The reported portfolio is the 30 highest *hospital* solo-loss crossings. Every result about schools and islanding is therefore conditional on a hospital-conditioned sample. Rebuilding the same-size portfolio under other rules tests that directly; islanding does not depend on the funded plan.

| Portfolio rule | Type mix | WF mean PD | Random mean PD | SPOF hospitals@60 | SPOF schools@45 |
|---|---|---|---|---|---|
| tag_first | culvert 29, minor_bridge 1 | 32,569 | 34,303 | 0 | 1 |
| bridge_tagged | culvert 30 | 53,690 | 53,718 | 0 | 1 |
| school_loss | culvert 24, minor_bridge 6 | 394,025 | 404,801 | 30 | 30 |

School criticality was measured on 804 candidate edges at a 45-minute cap.

### What an equity floor would cost

The plan reaches 114 of 114 habitations with any potential benefit. A hard floor on per-habitation benefit is degenerate on this portfolio (coverage is close to disjoint, so any unfunded hamlet holds the floor at zero), so the instrument is a weight on the objective instead: exponent 0 is the reported population-weighted plan, exponent 1 counts every habitation equally.

| Weight exponent | Funded | Spend (cr) | Total benefit | Gini | Reached | Efficiency lost |
|---|---|---|---|---|---|---|
| 0.00 | 16 | 0.500 | 18,164.0 | 0.451 | 70 | 0.0 |
| 0.50 | 16 | 0.500 | 17,718.4 | 0.440 | 79 | 445.6 |
| 1.00 | 16 | 0.500 | 17,398.3 | 0.439 | 77 | 765.7 |
| 1.50 | 13 | 0.500 | 15,751.3 | 0.403 | 80 | 2,412.7 |

### Two-year schedule against the receding-horizon plan

- two-period schedule: 50,320 person-days, planned Rs 1.000 cr, emergency Rs 2.286 cr
- receding-horizon additive plan: 44,106 person-days
- paired difference (schedule minus receding horizon): +6,214 (95% CI +3,132, +9,768)
- year-1 funded set overlap with the receding-horizon plan: Jaccard 0.84

### Solver quality

- 120 variables, 8 scenarios, 16 structures funded, objective 22,618.5
- reported MIP gap: 0.00e+00; status 0

Structures are unverified road/water screening candidates, not an asset register; condition, age, outage and cost are assumed and varied in E8. These are planning exercises, not observed condition or a spending recommendation.
