# E4 — do network effects matter? (additive MILP vs network-aware)

- corridors: 3, monsoon-stress rain ratio ~ e^0.9, budget Rs 0.4 crore
- each corridor: one habitation, `redundancy` parallel routes, one structure per route

## Mean person-days lost (lower is better)

| Redundancy | Do nothing | Worst-first | Benefit-cost | Additive MILP | Network-aware | Additive - Network |
|---|---|---|---|---|---|---|
| 1 | 26005 | 15824 | 21467 | 7237 | 7237 | +0 |
| 2 | 15579 | 5643 | 15579 | 15579 | 2821 | +12757 |
| 3 | 10304 | 4907 | 10304 | 10304 | 3557 | +6747 |
| 4 | 8709 | 2821 | 8709 | 8709 | 2453 | +6256 |

**Reading (honest):**
1. **Network effects matter.** At redundancy >= 2 every structure's solo loss is zero,
   so the *additive MILP does nothing* — it equals do-nothing exactly (15,579, 10,304, 8,709 person-days) — while the network-aware objective still finds real
   reductions of 12,757, 6,747, 6,256 person-days. At redundancy 1 the two agree, because
   additive already suffices when every structure is critical. That is E4.
2. **Condition-first is ahead nowhere now.** Network-aware is at or below worst-first at every redundancy: r=1 7,237 vs 15,824, r=2 2,821 vs 5,643, r=3 3,557 vs 4,907, r=4 2,453 vs 2,821.
   The earlier gap came from a budget-binding single-move search; two-asset swap
   moves, seeded restarts and out-of-sample candidate selection closed it (the
   surrogate is a rare-event estimator, so a plan must not be chosen on the sample
   it was tuned on).
3. The absolute loss falls as redundancy grows (joint failure gets rarer), so the
   additive-network *gap* is largest at moderate redundancy rather than at high r.

Note: repairs carry the direct fragility effect from plan 5.5 in the simulator, as
the optimizer's instance builder already assumed.
