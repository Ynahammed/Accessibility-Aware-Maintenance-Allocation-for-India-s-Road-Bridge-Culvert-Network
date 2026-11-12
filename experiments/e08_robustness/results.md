# E8 — robustness and regret across the assumptions register

- assumption sets sampled: 8
- scenarios x years: 20 x 4
- budget: Rs 0.3 crore

| Policy | Win rate | Mean regret | Max regret |
|---|---|---|---|
| do_nothing | 0.00 | 22076.92 | 49138.06 |
| worst_first | 0.00 | 25798.80 | 53840.86 |
| benefit_cost | 0.62 | 169.27 | 556.35 |
| additive_milp | 0.00 | 2084.56 | 5877.79 |
| network_aware | 0.38 | 1920.81 | 9403.66 |

## Primary metric per assumption set (person-days per crore)

| Assumption set | do_nothing | worst_first | benefit_cost | additive_milp | network_aware |
|---|---|---|---|---|---|
| 0 | 180398.4 | 185101.2 | 131260.3 | 137138.1 | 140664.0 | (benefit_cost)
| 1 | 109159.4 | 102412.6 | 74229.2 | 75837.6 | 75233.2 | (benefit_cost)
| 2 | 109210.8 | 112784.4 | 75966.3 | 77149.2 | 77178.4 | (benefit_cost)
| 3 | 123622.4 | 131115.0 | 97070.5 | 98332.6 | 96514.2 | (network_aware)
| 4 | 79353.6 | 90746.8 | 65463.1 | 69141.8 | 68501.1 | (benefit_cost)
| 5 | 38259.2 | 42336.8 | 33175.7 | 33715.8 | 33884.4 | (benefit_cost)
| 6 | 80862.4 | 86858.8 | 70023.7 | 70653.5 | 69700.7 | (network_aware)
| 7 | 17983.7 | 17269.4 | 16399.8 | 16942.5 | 15925.0 | (network_aware)
