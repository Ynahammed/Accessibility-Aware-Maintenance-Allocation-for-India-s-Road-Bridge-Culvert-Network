# Population denominators — reconciled

Indian sources only: Census 2011 rural village PCA, official Census district totals, and
the PMGSY GeoSadak habitation field. This documents why the two population totals differ
and what that does to the analyses that use them.

## The numbers

| Source | Universe | Records | Population |
|---|---|---|---|
| Census 2011 village PCA | rural villages only | 52 | 979,643 |
| Census 2011 district (official) | district total | — | 2,127,789 |
| Census 2011 district (official) | urban only | — | 1,148,146 |
| PMGSY GeoSadak habitations | district habitations | 1,981 | 2,169,418 |

PMGSY / district total = **1.020** (+2.0%).
PMGSY / rural village subtotal = **2.21x**.

So the two do not conflict: the earlier 2.2x comparison set a district-wide habitation
layer against a rural-only village subtotal. The urban population (1,148,146) has no
village row in that PCA file.

## Where the real problem is: the crosswalk, not the totals

- Villages with matched PMGSY points: 22 of 52.
- PMGSY points matched to a village: 28 of 1,981.
- PMGSY population inside matched villages: 34,173 (1.6% of the field).
- Median PMGSY population as a share of the matched village's Census total: 7.6% (p10 2.1%, p90 15.5%).

Two things follow. First, the PMGSY layer is not village-total duplication: within matched
villages its points cover only a fraction of village population, as expected for a layer of
individual habitations. Second, the name crosswalk is far too weak to move population
between the two sources: most PMGSY population sits in habitations that matched no village
row, so village-level reweighting is not defensible.

## What this means for the access and exposure numbers

- Census-based access results describe 979,643 rural residents, of whom
541,961 (55.3%) have no
  defensible coordinate. That is 25.5% of the district total, not 55%.
- The 2,169,418-person PMGSY field is a district-wide proxy with an unspecified
  vintage; it should be described as such, never as the Census total.
- The two totals must not be added, averaged, or used interchangeably as denominators.

## Limits

This reconciles totals and crosswalk coverage; it cannot separate 2011-vintage drift from
coverage differences in the PMGSY field, and neither source reflects current population.

Per-village detail is in `village_population_reconciliation.csv`; aggregates are in
`summary.json`.
