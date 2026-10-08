# E1 — deterioration models on real NBI data

- panel rows: 582014, structure-year pairs: 480753
- train pairs (year <= 2020): 287121
- test pairs  (year >= 2022): 97098
- years loaded: [2018, 2019, 2020, 2021, 2022, 2023]

| Model | Log-loss | RPS | Accuracy |
|---|---|---|---|
| M0_markov | 0.1636 | 0.0353 | 0.965 |
| M1_gbm | 0.1772 | 0.0366 | 0.964 |
| climatology | 0.8107 | 0.2792 | 0.471 |

Lower log-loss / RPS is better. M0 is the agency-style baseline; M1 must beat it
*and* the climatology baseline to support the plan's claim that ML models help.
