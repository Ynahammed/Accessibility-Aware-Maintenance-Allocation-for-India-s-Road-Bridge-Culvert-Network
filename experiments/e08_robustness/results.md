# E8 — robustness and regret across the assumptions register

- assumption sets sampled: 8
- scenarios x years: 20 x 4
- budget: Rs 0.3 crore

| Policy | Win rate | Mean regret | Max regret |
|---|---|---|---|
| do_nothing | 0.00 | 17627.11 | 36266.87 |
| worst_first | 0.00 | 20188.04 | 37890.10 |
| benefit_cost | 0.88 | 159.29 | 1274.29 |
| additive_milp | 0.00 | 1285.50 | 2987.71 |
| network_aware | 0.12 | 1370.65 | 3229.85 |

## Primary metric per assumption set (person-days per crore)

| Assumption set | do_nothing | worst_first | benefit_cost | additive_milp | network_aware |
|---|---|---|---|---|---|
| 0 | 180398.4 | 182021.6 | 144131.5 | 145989.5 | 146179.9 | (benefit_cost)
| 1 | 109159.4 | 102822.6 | 76935.5 | 78649.0 | 75661.2 | (network_aware)
| 2 | 109210.8 | 112334.7 | 83666.8 | 84446.3 | 84258.6 | (benefit_cost)
| 3 | 123622.4 | 130816.0 | 101904.5 | 103335.1 | 102488.6 | (benefit_cost)
| 4 | 79353.6 | 89346.6 | 71193.6 | 73064.8 | 74423.4 | (benefit_cost)
| 5 | 38259.2 | 40741.7 | 34029.2 | 34639.5 | 35770.2 | (benefit_cost)
| 6 | 80862.4 | 83894.6 | 70551.0 | 70741.8 | 72533.2 | (benefit_cost)
| 7 | 17983.7 | 17359.5 | 16695.2 | 17251.0 | 17482.8 | (benefit_cost)
