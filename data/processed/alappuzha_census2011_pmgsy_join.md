# Alappuzha Census 2011 ↔ PMGSY habitation join

## Sources and method

- Census: `data/raw/census/2011/DDW_PCA3211_2011_MDDS_with_UI.xlsx`; [ORGI Census of India 2011 PCA-TV, Alappuzha](https://censusindia.gov.in/nada/index.php/catalog/6789) (district code 598).
- PMGSY: `data/raw/pmgsy/Habitation_Kerala.zip`; [PMGSY GeoSadak Open Data](https://pmgsygeosadak.dord.gov.in/OpenData), Kerala habitation point layer; source IDs are PMGSY IDs, not Census village codes.
- Boundary: `data/raw/boundaries/kerala_districts_census_2011.geojson`; Alappuzha polygon selected by Census district code 598. Source: [geohacker/kerala](https://github.com/geohacker/kerala), based on [DataMeet district boundaries](https://github.com/datameet/maps), repository source last updated in 2018; boundary vintage may differ from the 2011 Census and PMGSY layer, so this is a spatial filter, not a legal boundary determination.
- Spatial selection: valid WGS84 PMGSY point coordinates strictly within the Alappuzha polygon.
- Name match: normalized English names (case, whitespace and punctuation normalized); qualifiers such as '(Part)' are retained. No fuzzy matching or forced assignment. Census village codes do not exist in the PMGSY habitation file.
- A PMGSY habitation point is finer than a Census village; a village population is retained once per Census village, not duplicated across habitation points.

## Counts

- Census rural village rows: 52; population total: 979,643 (Census 2011).
- PMGSY habitation points spatially in boundary: 1,981; invalid/out-of-range coordinates excluded before spatial selection: 1.
- Census villages with an exact normalized-name match: 22/52; matched village population: 437,682 (44.7% of Census rural population).
- Matched PMGSY habitation point records: 28; these are not independent Census population observations.
- Unmatched Census villages: 30; unmatched Census population: 541,961.
- Unmatched PMGSY habitation point records: 1,953; distinct normalized unmatched names: 1,743 (record-level detail is in the point crosswalk CSV).

## Unmatched Census village records

- Perumbalam (Census village code 628206): 9,733 people
- Panavally (Census village code 628207): 31,570 people
- Pattanakkad (Census village code 628209): 31,629 people
- Kadakkarappally (Census village code 628210): 20,487 people
- Cherthala North (Part) (Census village code 628211): 13,945 people
- Cherthala South (Part) (Census village code 628212): 26,157 people
- Mararikkulam North (Census village code 628213): 31,322 people
- Aryad South  (Part) (Census village code 628227): 0 people
- Mullakkal (Part) (Census village code 628228): 497 people
- Ambalappuzha (Census village code 628229): 33,939 people
- Kainakary North (Census village code 628236): 8,292 people
- Kainakary South (Census village code 628237): 15,405 people
- Pulinkunnu (Census village code 628238): 15,210 people
- Neelamperoor (Census village code 628241): 5,841 people
- Veliyanad (Census village code 628242): 12,501 people
- Champakkulam (Census village code 628244): 15,848 people
- Thakazhy (Census village code 628246): 15,758 people
- Pallippad (Census village code 628253): 24,648 people
- Ennakkad (Census village code 628267): 18,444 people
- Pandanad (Part) (Census village code 628268): 11,489 people
- Chengannur  (Part) (Census village code 628270): 1,989 people
- Mulakuzha (Part) (Census village code 628271): 28,390 people
- Ala (Part) (Census village code 628272): 13,665 people
- Puliyoor(Part) (Census village code 628273): 16,531 people
- Venmony (Census village code 628275): 19,932 people
- Thriperumthura (Census village code 628278): 15,226 people
- Vettiyar (Census village code 628279): 21,393 people
- Thekkekara (Part) (Census village code 628280): 32,373 people
- Chunakkara (Census village code 628282): 22,730 people
- Thamarakkulam (Census village code 628285): 27,017 people

## Interpretation and limitations

This is a conservative **name-based crosswalk**, not a one-to-one population join. Census villages and PMGSY habitations are different geographic units. A matched Census population is a contextual village-level demand total, not population assigned to each PMGSY point. The 22 matched village records account for 437,682 people; do not sum that population once per matching habitation point. The 30 unmatched villages and 541,961 people remain visible in the CSV.

The PMGSY layer has 30,148 points for all Kerala. After spatial selection, 1,981 are inside the chosen polygon; 1,914 carry PMGSY internal district ID 8 and 67 carry other internal IDs. Those 67 points have an internal district ID that disagrees with the spatial filter; both are preserved in the output rather than silently discarded. The PMGSY population field is a distinct source field and is not substituted for Census population.

- PMGSY point crosswalk rows: `data/processed/alappuzha_pmgsy_habitations_census_crosswalk.csv`; this file includes all in-boundary PMGSY points and matched Census village codes, but intentionally does not repeat Census village population across points.
- Census village summary: `data/processed/alappuzha_census2011_pmgsy_join.csv`.
