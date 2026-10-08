# E4 — do network effects matter? (additive MILP vs network-aware)

- corridors: 3, monsoon-stress rain ratio ~ e^0.9, budget Rs 0.4 crore
- each corridor: one habitation, `redundancy` parallel routes, one structure per route

## Mean person-days lost (lower is better)

| Redundancy | Do nothing | Worst-first | Benefit-cost | Additive MILP | Network-aware | Additive - Network |
|---|---|---|---|---|---|---|
| 1 | 26005 | 19381 | 24901 | 19381 | 19381 | +0 |
| 2 | 15579 | 8709 | 15579 | 15579 | 10795 | +4784 |
| 3 | 10304 | 6501 | 10304 | 10304 | 7851 | +2453 |
| 4 | 8709 | 4293 | 8709 | 8709 | 6133 | +2576 |

**Reading:** at redundancy 1 every structure is critical and the additive model
captures it, so the two optimizers agree. As redundancy grows a repair only helps by
preventing *joint* failure, which the additive model cannot see (solo loss is zero) —
the gap is where network-aware allocation earns its keep.
