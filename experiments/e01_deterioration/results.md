# E1 — ARCHIVED: US NBI deterioration (out of scope)

> **This experiment is not Indian evidence.** It was fitted to US FHWA National Bridge
> Inventory records (AL/CA/TX, 2018–2023). The project now works on Indian data only, so E1
> is retained for provenance and is no longer loaded by the dashboard or `/api/evidence`.
> Do not cite these numbers as evidence about Indian bridges, and do not reuse this result
> as a validation of an India-facing deterioration model.

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
