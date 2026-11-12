# E3 — accessibility-aware vs condition-based allocation

- district: 14 habitations, 10 structures
- scenarios: 40, years: 5
- budget: Rs 0.6 crore, crew: 400.0 crew-days

| Policy | Mean person-days | Mean spend (cr) | Person-days per crore | CVaR |
|---|---|---|---|---|
| additive_milp | 131816.5 | 11.21 | 11760.5 | 234136.1 |
| network_aware | 133638.2 | 11.29 | 11835.9 | 247712.7 |
| random | 208551.7 | 12.32 | 16934.5 | 317286.1 |
| benefit_cost | 208551.7 | 12.32 | 16934.5 | 317286.1 |
| worst_first | 199737.9 | 11.24 | 17776.0 | 320299.8 |
| criticality_weighted | 199737.9 | 11.24 | 17776.0 | 320299.8 |
| siloed | 240898.4 | 11.57 | 20817.0 | 370382.5 |
| do_nothing | 257791.8 | 12.06 | 21372.6 | 398511.9 |

**Paired (same scenarios):** worst-first minus network-aware = 66099.7 person-days, 95% CI [53262.9, 79654.0]. Positive = the proposed method loses fewer person-days.
