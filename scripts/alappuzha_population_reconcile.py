"""Reconcile the Indian population denominators used in the Alappuzha analyses.

The project carries two population sources and they are often compared wrongly:

* Census 2011 Primary Census Abstract, village rows: this file is the **rural** PCA for
  Alappuzha — 52 rural villages, 979,643 people. The district total is 2,127,789
  (rural 979,643 + urban 1,148,146), and urban wards are not village rows.
* PMGSY GeoSadak habitation points: the district-wide habitation layer, total 2,169,418 in
  the source `TOT_POPULA` field.

2,169,418 / 2,127,789 = 1.020, i.e. the PMGSY field is within ~2% of the **district**
total, and is 2.21x the **rural** village subtotal. That ratio is not double counting; it is
a universe difference (rural-only PCA vs district-wide habitations). This script records the
check, and quantifies how much of each village the PMGSY layer actually represents.

Run: python scripts/alappuzha_population_reconcile.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
JOIN = ROOT / "data/processed/alappuzha_network_join"
OUT = ROOT / "data/processed/alappuzha_population_reconcile"

# Official Census 2011 totals for Alappuzha district (ORGI district rural-urban distribution).
CENSUS_DISTRICT_TOTAL = 2_127_789
CENSUS_DISTRICT_RURAL = 979_643
CENSUS_DISTRICT_URBAN = 1_148_146


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    habitations = pd.read_parquet(
        JOIN / "pmgsy_habitations_snapped.parquet",
        columns=[
            "entity_id",
            "pmgsy_population_field",
            "census_village_code",
            "crosswalk_status",
            "attached_to_network",
        ],
    )
    villages = pd.read_parquet(
        JOIN / "census_villages_snapped.parquet",
        columns=["census_village_code", "census_village_name", "census_population_2011", "longitude"],
    )

    pmgsy_total = int(habitations.pmgsy_population_field.sum())
    census_rural = int(villages.census_population_2011.sum())
    if census_rural != CENSUS_DISTRICT_RURAL:
        raise SystemExit(
            f"village rows sum to {census_rural:,}, expected the rural subtotal "
            f"{CENSUS_DISTRICT_RURAL:,}; the PCA file may have changed"
        )

    per_village = (
        habitations.groupby("census_village_code")
        .agg(
            pmgsy_points=("entity_id", "size"),
            pmgsy_population=("pmgsy_population_field", "sum"),
            distinct_population_values=("pmgsy_population_field", "nunique"),
        )
        .reset_index()
    )
    per_village["census_village_code"] = per_village.census_village_code.astype("string")
    villages["census_village_code"] = villages.census_village_code.astype("string")
    per_village = villages.merge(per_village, on="census_village_code", how="left")
    per_village["pmgsy_share_of_village"] = (
        per_village.pmgsy_population / per_village.census_population_2011
    )
    per_village["has_coordinate"] = per_village.longitude.notna()
    per_village = per_village.drop(columns=["longitude"])
    per_village.to_csv(OUT / "village_population_reconciliation.csv", index=False)

    matched = per_village[per_village.pmgsy_population.notna()].copy()
    located = per_village[per_village.has_coordinate]

    summary = {
        "title": "Alappuzha population denominator reconciliation (Indian sources only)",
        "sources": {
            "census_village_pca": {
                "file": "data/raw/census/2011/DDW_PCA3211_2011_MDDS_with_UI.xlsx",
                "universe": "rural villages only",
                "village_rows": int(len(villages)),
                "population": census_rural,
            },
            "census_district_official": {
                "total": CENSUS_DISTRICT_TOTAL,
                "rural": CENSUS_DISTRICT_RURAL,
                "urban": CENSUS_DISTRICT_URBAN,
                "note": "ORGI Census 2011 district rural-urban distribution; urban wards are not village rows",
            },
            "pmgsy_habitations": {
                "field": "TOT_POPULA",
                "points": int(len(habitations)),
                "population": pmgsy_total,
            },
        },
        "ratios": {
            "pmgsy_over_district_total": pmgsy_total / CENSUS_DISTRICT_TOTAL,
            "pmgsy_over_rural_subtotal": pmgsy_total / CENSUS_DISTRICT_RURAL,
            "pmgsy_share_difference_from_district_total": pmgsy_total / CENSUS_DISTRICT_TOTAL - 1.0,
        },
        "crosswalk_coverage": {
            "villages": int(len(villages)),
            "villages_with_matched_pmgsy_points": int(len(matched)),
            "villages_without_match": int(len(villages) - len(matched)),
            "pmgsy_points_matched_to_a_village": int(matched.pmgsy_points.sum()),
            "pmgsy_points_unmatched": int(len(habitations) - matched.pmgsy_points.sum()),
            "pmgsy_population_inside_matched_villages": int(matched.pmgsy_population.sum()),
            "pmgsy_population_share_inside_matched_villages": float(
                matched.pmgsy_population.sum() / pmgsy_total
            ),
        },
        "village_representation": {
            "median_pmgsy_share_of_village_population": float(matched.pmgsy_share_of_village.median()),
            "p10": float(matched.pmgsy_share_of_village.quantile(0.10)),
            "p90": float(matched.pmgsy_share_of_village.quantile(0.90)),
            "max": float(matched.pmgsy_share_of_village.max()),
        },
        "located_villages": {
            "with_coordinate": int(len(located)),
            "without_coordinate": int(len(villages) - len(located)),
            "population_without_coordinate": int(
                per_village.loc[~per_village.has_coordinate, "census_population_2011"].sum()
            ),
            "share_of_rural_population_without_coordinate": float(
                per_village.loc[~per_village.has_coordinate, "census_population_2011"].sum() / census_rural
            ),
            "share_of_district_population_without_coordinate": float(
                per_village.loc[~per_village.has_coordinate, "census_population_2011"].sum()
                / CENSUS_DISTRICT_TOTAL
            ),
        },
        "conclusions": [
            "The PMGSY field is within about 2% of the Census 2011 district total, so it is a district-wide habitation layer, not a duplicate of the rural village PCA.",
            "The 2.2x gap that appears when the PMGSY total is compared with 979,643 is a universe difference: that figure is the rural village subtotal, while 1,148,146 urban residents are not village rows.",
            "The Census/PMGSY name crosswalk is the weak link, not the population totals: matched villages hold only a small fraction of PMGSY population, so village-level population attribution is unreliable even though district totals agree.",
            "Neither source is a substitute for the other: Census gives official totals with incomplete geocoding, PMGSY gives complete district geometry with a source field of unclear vintage. They must stay separate and never be added.",
        ],
        "caveats": [
            "The +2% difference is consistent with a 2011 vintage field plus coverage differences, but this analysis cannot separate vintage drift from coverage.",
            "Neither source is dated later than the Census 2011 baseline; neither reflects 2026 population.",
        ],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Population denominators — reconciled",
        "",
        "Indian sources only: Census 2011 rural village PCA, official Census district totals, and",
        "the PMGSY GeoSadak habitation field. This documents why the two population totals differ",
        "and what that does to the analyses that use them.",
        "",
        "## The numbers",
        "",
        "| Source | Universe | Records | Population |",
        "|---|---|---|---|",
        f"| Census 2011 village PCA | rural villages only | {len(villages)} | {census_rural:,} |",
        f"| Census 2011 district (official) | district total | — | {CENSUS_DISTRICT_TOTAL:,} |",
        f"| Census 2011 district (official) | urban only | — | {CENSUS_DISTRICT_URBAN:,} |",
        f"| PMGSY GeoSadak habitations | district habitations | {len(habitations):,} | {pmgsy_total:,} |",
        "",
        f"PMGSY / district total = **{pmgsy_total / CENSUS_DISTRICT_TOTAL:.3f}** "
        f"({pmgsy_total / CENSUS_DISTRICT_TOTAL - 1:+.1%}).",
        f"PMGSY / rural village subtotal = **{pmgsy_total / CENSUS_DISTRICT_RURAL:.2f}x**.",
        "",
        "So the two do not conflict: the earlier 2.2x comparison set a district-wide habitation",
        "layer against a rural-only village subtotal. The urban population (1,148,146) has no",
        "village row in that PCA file.",
        "",
        "## Where the real problem is: the crosswalk, not the totals",
        "",
        f"- Villages with matched PMGSY points: {len(matched)} of {len(villages)}.",
        f"- PMGSY points matched to a village: {int(matched.pmgsy_points.sum()):,} of "
        f"{len(habitations):,}.",
        f"- PMGSY population inside matched villages: {int(matched.pmgsy_population.sum()):,} "
        f"({matched.pmgsy_population.sum() / pmgsy_total:.1%} of the field).",
        f"- Median PMGSY population as a share of the matched village's Census total: "
        f"{matched.pmgsy_share_of_village.median():.1%} "
        f"(p10 {matched.pmgsy_share_of_village.quantile(0.10):.1%}, "
        f"p90 {matched.pmgsy_share_of_village.quantile(0.90):.1%}).",
        "",
        "Two things follow. First, the PMGSY layer is not village-total duplication: within matched",
        "villages its points cover only a fraction of village population, as expected for a layer of",
        "individual habitations. Second, the name crosswalk is far too weak to move population",
        "between the two sources: most PMGSY population sits in habitations that matched no village",
        "row, so village-level reweighting is not defensible.",
        "",
        "## What this means for the access and exposure numbers",
        "",
        f"- Census-based access results describe {census_rural:,} rural residents, of whom "
        f"{summary['located_villages']['population_without_coordinate']:,} "
        f"({summary['located_villages']['share_of_rural_population_without_coordinate']:.1%}) have no "
        "defensible coordinate. That is "
        f"{summary['located_villages']['share_of_district_population_without_coordinate']:.1%} "
        "of the district total, not 55%.",
        f"- The {pmgsy_total:,}-person PMGSY field is a district-wide proxy with an unspecified",
        "  vintage; it should be described as such, never as the Census total.",
        "- The two totals must not be added, averaged, or used interchangeably as denominators.",
        "",
        "## Limits",
        "",
        "This reconciles totals and crosswalk coverage; it cannot separate 2011-vintage drift from",
        "coverage differences in the PMGSY field, and neither source reflects current population.",
        "",
        "Per-village detail is in `village_population_reconciliation.csv`; aggregates are in",
        "`summary.json`.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
