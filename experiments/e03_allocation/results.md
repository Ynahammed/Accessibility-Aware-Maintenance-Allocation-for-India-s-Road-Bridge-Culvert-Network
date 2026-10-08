# E3 — accessibility-aware vs condition-based allocation

- district: 14 habitations, 10 structures
- scenarios: 40, years: 5
- budget: Rs 0.6 crore, crew: 400.0 crew-days

| Policy | Mean person-days | Mean spend (cr) | Person-days per crore | CVaR |
|---|---|---|---|---|
| additive_milp | 151724.9 | 11.88 | 12774.4 | 260715.5 |
| network_aware | 151628.6 | 11.79 | 12863.4 | 260715.5 |
| random | 217199.4 | 12.89 | 16844.0 | 347808.0 |
| benefit_cost | 217199.4 | 12.89 | 16844.0 | 347808.0 |
| worst_first | 204436.2 | 11.62 | 17591.0 | 337656.2 |
| criticality_weighted | 204436.2 | 11.62 | 17591.0 | 337656.2 |
| siloed | 240225.0 | 11.67 | 20593.7 | 368844.3 |
| do_nothing | 257791.8 | 12.06 | 21372.6 | 398511.9 |

**Paired (same scenarios):** worst-first minus network-aware = 52807.6 person-days, 95% CI [41031.3, 64767.7]. Positive = the proposed method loses fewer person-days.
