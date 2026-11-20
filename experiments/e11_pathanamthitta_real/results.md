# E9 — real Pathanamthitta network: allocation, inspection value, islanding

- instance: 2129 habitations, 30 structures, population 1098743
- structure mix: {'culvert': 30}
- habitations already beyond the 60-minute health cap before any failure: 22
- scenarios: 8, years: 2, budget Rs 0.5 cr, crew 150.0 days

## Policy panel (paired scenarios)

| Policy | Mean person-days | Spend (cr) | Person-days per crore | CVaR | Funded yr-1 |
|---|---|---|---|---|---|
| additive_milp | 39631.3 | 3.23 | 12262.2 | 48574.7 | 16 |
| benefit_cost | 45998.2 | 3.34 | 13771.9 | 56711.3 | 25 |
| random | 47398.7 | 3.34 | 14191.2 | 59388.7 | 25 |
| worst_first | 45229.1 | 3.14 | 14427.2 | 59423.5 | 13 |
| do_nothing | 64640.4 | 3.33 | 19411.5 | 74191.2 | 0 |

**Paired additive_milp - worst_first**: -5597.8 person-days, 95% CI [-8894.9, -1951.1] (positive = first is worse).

**Paired additive_milp - do_nothing**: -25009.1 person-days, 95% CI [-30401.3, -19585.6] (positive = first is worse).

**Comparators built, not assumed.** All 30 screened structures are culverts, so `siloed`'s per-class split is a no-op, and `criticality_weighted` ranks on a criticality proxy of 1 + condition, which orders assets similarly to condition but not identically once intervention costs differ. The three condition-based policies select the identical funded set at Rs 0.1 cr, Rs 0.25 cr, Rs 1 cr. They differ at Rs 0.5 cr: same count, different assets. The identity is therefore a property of this portfolio *and* budget, and only worst-first is reported at the panel's own budget.

Scenario win rate (share of scenarios where the policy loses fewest person-days): additive_milp 75%, worst_first 12%, random 12%, do_nothing 0%, benefit_cost 0%

## Condition-first practice against chance

| Metric | Condition-first | Random | Difference |
|---|---|---|---|
| Mean person-days lost | 45,229 | 47,399 | -2,170 |
| Mean spend, planned + emergency (Rs cr) | 3.14 | 3.34 | -0.21 |
| Person-days lost per crore | 14,427 | 14,191 | +236 |

Paired on the same 8 scenarios, condition-first minus random is -2,170 person-days (95% CI [-7,403, +3,395]); it loses fewer person-days in 62% of scenarios and more in 38%. The two metrics disagree in sign because random funds 25 cheaper structures and so spends more: condition-first is ahead in absolute loss, behind per crore. Either way the gap is 39% of the 5,598 person-days that accessibility-aware allocation recovers against the same baseline. On this network condition-first ranking performs close to chance, which is a stronger motivation for the method than the method's own win.

## Inspection value (which structure's condition is worth resolving)

| Structure | Type | Assumed | Plan gain | Plan changes in states |
|---|---|---|---|---|
| X003 | culvert | 1 | 659.2 | 1/3 |
| X011 | culvert | 1 | 659.2 | 1/3 |
| X004 | culvert | 1 | 642.4 | 1/3 |
| X005 | culvert | 1 | 609.6 | 1/3 |
| X017 | culvert | 1 | 570.2 | 1/3 |
| X019 | culvert | 1 | 466.6 | 1/3 |
| X023 | culvert | 1 | 424.6 | 1/3 |
| X018 | culvert | 1 | 406.1 | 1/3 |
| X025 | culvert | 1 | 379.4 | 1/3 |
| X022 | culvert | 1 | 371.6 | 1/3 |

Sum of positive gains: 5189.0 (base objective 18884.2).

## Single points of failure

0 of 30 structures cut any habitation off from a hospital when failing alone.

| Structure | Isolated habitations | Isolated population | Max extra one-way minutes |
|---|---|---|---|
| X001 | 0 | 0 | 16 |
| X002 | 0 | 0 | 8 |
| X003 | 0 | 0 | 3 |
| X004 | 0 | 0 | 5 |
| X005 | 0 | 0 | 7 |
| X006 | 0 | 0 | 5 |
| X007 | 0 | 0 | 3 |
| X008 | 0 | 0 | 5 |
| X009 | 0 | 0 | 2 |
| X010 | 0 | 0 | 3 |

## Benefit distribution

- habitations reached: 118 (7% of population)
- Gini of benefit per person: 0.544
- top 1% share of benefit: 0.00

## Destination sensitivity: hospitals against schools

Isolation depends on what counts as a destination. The audit above uses hospitals only — the most forgiving set in the district — so this repeats it with the school layer (schools, colleges, kindergartens) on the same 30 structures, the same graph and the same funded plan. No market layer exists to test: the OSM extract contains no `amenity=marketplace` points.

| Destination | Points | Cap (min) | Median access | Within cap | SPOF | Isolated population | Benefit Gini |
|---|---|---|---|---|---|---|---|
| health | 304 | 60 | 3.3 | 98.6% | 0 | 0 | 0.544 |
| school | 987 | 45 | 2.0 | 99.5% | 1 | 1,452 | 0.593 |

The school tier reuses the hospital-optimised funded plan, so its benefit split answers a distributional question about that plan rather than re-solving the optimiser for schools; the isolation counts are independent of the plan.

## Budget frontier (plan objective)

| Budget (cr) | Objective | Loss per crore | Funded |
|---|---|---|---|
| 0.10 | 27439.9 | 274398.9 | 5 |
| 0.25 | 23930.9 | 95723.8 | 9 |
| 0.50 | 18884.2 | 37768.3 | 16 |
| 1.00 | 14254.1 | 14254.1 | 15 |

## Robustness of the headline finding

### Equal planned spend

The panel above lets each rule spend what it chooses, so the absolute and per-crore readings can disagree in sign. Here every policy faces the same planned budget, including the budget at which condition-first actually spends at the reporting setting. Emergency restoration is reported but not equalised: it follows failure, it is not an allocation choice.

| Budget/yr (cr) | Policy | Mean person-days | Planned (cr) | Emergency (cr) | Funded |
|---|---|---|---|---|---|
| 0.250 | worst_first | 53,453 | 0.388 | 2.664 | 10 |
| 0.250 | random | 55,881 | 0.480 | 2.754 | 12 |
| 0.250 | benefit_cost | 54,036 | 0.480 | 2.916 | 12 |
| 0.250 | additive_milp | 56,438 | 0.480 | 2.988 | 9 |
| 0.398 | worst_first | 46,717 | 0.643 | 2.430 | 12 |
| 0.398 | random | 50,484 | 0.760 | 2.556 | 19 |
| 0.398 | benefit_cost | 50,409 | 0.760 | 2.610 | 19 |
| 0.398 | additive_milp | 44,098 | 0.760 | 2.520 | 13 |
| 0.500 | worst_first | 45,229 | 0.795 | 2.340 | 13 |
| 0.500 | random | 47,399 | 1.000 | 2.340 | 25 |
| 0.500 | benefit_cost | 45,998 | 1.000 | 2.340 | 25 |
| 0.500 | additive_milp | 39,631 | 1.000 | 2.232 | 16 |

Matched-spend comparison of condition-first against random:

| Budget/yr (cr) | WF planned | Random planned | Gap | Paired WF-random (95% CI) | WF better in |
|---|---|---|---|---|---|
| 0.250 | 0.388 | 0.480 | -0.093 | -2,427 (-5,436, +386) | 62% |
| 0.398 | 0.643 | 0.760 | -0.118 | -3,767 (-8,641, +1,203) | 62% |
| 0.500 | 0.795 | 1.000 | -0.205 | -2,170 (-7,403, +3,395) | 62% |

### Equivalence and precision

A confidence interval containing zero is not evidence of equivalence. The margin here is a share of what the additive policy recovers against condition-first, so the test asks whether practice is within a *policy-relevant* distance of chance.

| Scenarios | WF-random | SD | MDE | Additive gain | Margin | TOST p | Verdict | n required |
|---|---|---|---|---|---|---|---|---|
| 8 | -2,170 | 8,470 | 7,081 | 5,598 | 280 (5%) | 0.726 | inconclusive | 5662 |
| 8 | -2,170 | 8,470 | 7,081 | 5,598 | 560 (10%) | 0.696 | inconclusive | 1416 |
| 40 | -4,335 | 7,411 | 2,370 | 981 | 49 (5%) | 1.000 | inconclusive | 141132 |
| 40 | -4,335 | 7,411 | 2,370 | 981 | 98 (10%) | 1.000 | inconclusive | 35283 |

An 'inconclusive' verdict means the design cannot demonstrate equivalence at that margin; `n required` is the paired scenario count a TOST at that margin would need at 80% power. The honest claim is therefore that practice is not distinguishable from chance and that the design is underpowered to claim more.

### Consequence-blind rules, not one baseline

| Rule | Mean person-days | Planned (cr) | Funded | Paired vs random (95% CI) | Better in |
|---|---|---|---|---|---|
| type_first | 53,267 | 1.000 | 3 | +5,868 (+2,447, +9,223) | 12% |
| random | 47,399 | 1.000 | 25 | - | - |
| worst_first | 45,229 | 0.795 | 13 | -2,170 (-7,403, +3,395) | 62% |
| cheapest_first | 45,229 | 0.795 | 13 | -2,170 (-7,403, +3,395) | 62% |
| road_class_first | 55,831 | 0.992 | 3 | +8,432 (+6,696, +10,339) | 0% |
| age_first | 55,741 | 0.992 | 5 | +8,342 (+5,186, +12,123) | 0% |
| do_nothing | 64,640 | 0.000 | 0 | - | - |

Every rule here buys the condition-appropriate intervention, so the comparison is about the ranking signal alone. None of them uses a consequence measure.

### Destination and travel-time cap, swept together

| Destination | Cap (min) | Points | Median access | Within cap | SPOF | Isolated people (summed) | Benefit Gini |
|---|---|---|---|---|---|---|---|
| health | 30 | 304 | 3.3 | 98.6% | 0 | 0 | 0.544 |
| health | 45 | 304 | 3.3 | 98.6% | 0 | 0 | 0.544 |
| health | 60 | 304 | 3.3 | 98.6% | 0 | 0 | 0.544 |
| health | 90 | 304 | 3.3 | 98.6% | 0 | 0 | 0.544 |
| school | 30 | 987 | 2.0 | 99.5% | 1 | 1,452 | 0.593 |
| school | 45 | 987 | 2.0 | 99.5% | 1 | 1,452 | 0.593 |
| school | 60 | 987 | 2.0 | 99.5% | 1 | 1,452 | 0.593 |
| school | 90 | 987 | 2.0 | 99.5% | 1 | 1,452 | 0.593 |

The hospital-at-60 cell is the most forgiving one in this table: sparsest destination set, loosest cap. Comparing cells separates the destination set from the cap, which a single hospital-versus-school pair cannot do.

### Does the selection rule drive the result?

The reported portfolio is the 30 highest *hospital* solo-loss crossings. Every result about schools and islanding is therefore conditional on a hospital-conditioned sample. Rebuilding the same-size portfolio under other rules tests that directly; islanding does not depend on the funded plan.

| Portfolio rule | Type mix | WF mean PD | Random mean PD | SPOF hospitals@60 | SPOF schools@45 |
|---|---|---|---|---|---|
| tag_first | culvert 30 | 21,961 | 23,082 | 0 | 1 |
| bridge_tagged | culvert 30 | 31,388 | 34,898 | 0 | 0 |
| school_loss | culvert 30 | 140,798 | 147,196 | 27 | 30 |

School criticality was measured on 1,039 candidate edges at a 45-minute cap.

### What an equity floor would cost

The plan reaches 203 of 203 habitations with any potential benefit. A hard floor on per-habitation benefit is degenerate on this portfolio (coverage is close to disjoint, so any unfunded hamlet holds the floor at zero), so the instrument is a weight on the objective instead: exponent 0 is the reported population-weighted plan, exponent 1 counts every habitation equally.

| Weight exponent | Funded | Spend (cr) | Total benefit | Gini | Reached | Efficiency lost |
|---|---|---|---|---|---|---|
| 0.00 | 16 | 0.500 | 14,411.8 | 0.575 | 118 | 0.0 |
| 0.50 | 16 | 0.500 | 14,349.3 | 0.552 | 122 | 62.6 |
| 1.00 | 16 | 0.500 | 13,808.4 | 0.481 | 128 | 603.5 |
| 1.50 | 13 | 0.500 | 12,826.0 | 0.439 | 111 | 1,585.9 |

### Two-year schedule against the receding-horizon plan

- two-period schedule: 44,962 person-days, planned Rs 1.000 cr, emergency Rs 2.322 cr
- receding-horizon additive plan: 39,631 person-days
- paired difference (schedule minus receding horizon): +5,331 (95% CI +3,176, +7,420)
- year-1 funded set overlap with the receding-horizon plan: Jaccard 0.75

### Solver quality

- 120 variables, 8 scenarios, 16 structures funded, objective 18,884.2
- reported MIP gap: 0.00e+00; status 0

Structures are unverified road/water screening candidates, not an asset register; condition, age, outage and cost are assumed and varied in E8. These are planning exercises, not observed condition or a spending recommendation.
