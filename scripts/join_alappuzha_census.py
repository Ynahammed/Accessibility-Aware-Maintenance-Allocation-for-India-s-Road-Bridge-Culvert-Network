"""Join Census 2011 Alappuzha village population to PMGSY habitation points.

Inputs are kept under data/raw:
- official Census of India 2011 Alappuzha PCA-TV Excel workbook
- PMGSY GeoSadak Kerala habitation shapefile archive
- Kerala ADM2 boundaries with Census 2011 district codes

A habitation-to-village join is name-based after spatially selecting the 2011
Alappuzha boundary. Census village codes do not occur in the PMGSY habitation
file. Multiple PMGSY points can match one village; village population is kept
once per Census village and is never summed across points.

Run: python scripts/join_alappuzha_census.py
"""
from __future__ import annotations

import json
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

import geopandas as gpd
import numpy as np
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
CENSUS_XLSX = ROOT / "data/raw/census/2011/DDW_PCA3211_2011_MDDS_with_UI.xlsx"
HABITATIONS_ZIP = ROOT / "data/raw/pmgsy/Habitation_Kerala.zip"
BOUNDARIES_GEOJSON = ROOT / "data/raw/boundaries/kerala_districts_census_2011.geojson"
OUTPUT = ROOT / "data/processed/alappuzha_census2011_pmgsy_join.csv"
POINT_OUTPUT = ROOT / "data/processed/alappuzha_pmgsy_habitations_census_crosswalk.csv"
REPORT = ROOT / "data/processed/alappuzha_census2011_pmgsy_join.md"

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _column(ref: str) -> str:
    return re.match(r"[A-Z]+", ref).group(0)


def read_census_villages(path: Path) -> list[dict[str, object]]:
    """Read the Census workbook's original text codes without Excel conversion."""
    with zipfile.ZipFile(path) as archive:
        shared = [
            "".join(t.text or "" for t in item.findall(".//m:t", NS))
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall(
                "m:si", NS
            )
        ]
        rows = []
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        for row in sheet.findall(".//m:sheetData/m:row", NS):
            values: dict[str, str] = {}
            for cell in row.findall("m:c", NS):
                value_node = cell.find("m:v", NS)
                value = value_node.text if value_node is not None else ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                values[_column(cell.attrib["r"])] = value
            rows.append(values)

    if not rows or rows[0].get("H") != "Name":
        raise ValueError(f"Unexpected Census workbook schema: {path}")

    villages = []
    for row in rows[1:]:
        if row.get("G") != "VILLAGE":
            continue
        villages.append(
            {
                "census_village_name": row.get("H", ""),
                "census_village_code": row.get("D", ""),
                "census_subdistrict_code": row.get("C", ""),
                "residence": row.get("I", ""),
                "census_population_2011": int(row.get("K") or 0),
            }
        )
    return villages


def normalize_name(value: object) -> str:
    """Normalize typography, retaining words such as '(Part)' as meaningful."""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def main() -> None:
    for path in (CENSUS_XLSX, HABITATIONS_ZIP, BOUNDARIES_GEOJSON):
        if not path.is_file():
            raise FileNotFoundError(path)

    with BOUNDARIES_GEOJSON.open(encoding="utf-8") as f:
        boundaries = json.load(f)
    boundary_feature = next(
        (
            feature
            for feature in boundaries["features"]
            if feature.get("properties", {}).get("censuscode") == 598
            and feature.get("properties", {}).get("DISTRICT") == "Alappuzha"
        ),
        None,
    )
    if boundary_feature is None:
        raise ValueError("Alappuzha boundary with Census district code 598 not found")
    boundary = shape(boundary_feature["geometry"])
    if not boundary.is_valid:
        raise ValueError("Alappuzha district boundary is invalid")

    habitations = gpd.read_file(f"zip://{HABITATIONS_ZIP.resolve().as_posix()}")
    if habitations.crs is None:
        raise ValueError("PMGSY habitation layer has no coordinate reference system")
    if habitations.crs.to_epsg() != 4326:
        habitations = habitations.to_crs("EPSG:4326")
    x = habitations.geometry.x
    y = habitations.geometry.y
    plausible_coordinates = (
        habitations.geometry.notna()
        & habitations.geometry.is_valid
        & np.isfinite(x)
        & np.isfinite(y)
        & x.between(-180, 180)
        & y.between(-90, 90)
    )
    points_in_district = habitations.loc[
        plausible_coordinates & habitations.geometry.within(boundary)
    ].copy()
    invalid_coordinate_rows = int((~plausible_coordinates).sum())

    census_villages = read_census_villages(CENSUS_XLSX)
    census_by_name: dict[str, list[dict[str, object]]] = defaultdict(list)
    for village in census_villages:
        census_by_name[normalize_name(village["census_village_name"])].append(village)

    habitation_counts = Counter(
        normalize_name(name) for name in points_in_district["HAB_NAME"]
    )
    # Ignore Census keys that collide after normalization; do not make an arbitrary join.
    unique_census_keys = {
        key: records[0] for key, records in census_by_name.items() if len(records) == 1
    }
    census_matches = {
        key: village for key, village in unique_census_keys.items() if habitation_counts[key]
    }

    rows = []
    for village in census_villages:
        key = normalize_name(village["census_village_name"])
        duplicate_census_name = len(census_by_name[key]) != 1
        point_count = habitation_counts[key] if not duplicate_census_name else 0
        status = (
            "ambiguous_census_name"
            if duplicate_census_name
            else "matched_exact_normalized_name"
            if point_count
            else "unmatched_census_village"
        )
        rows.append(
            {
                **village,
                "pmgsy_habitation_point_count": point_count,
                "match_status": status,
                "population_interpretation": (
                    "Census village population is a village total; do not copy/sum per habitation"
                    if point_count
                    else "no PMGSY habitation-name match found"
                ),
            }
        )

    matched_villages = [
        village
        for village in census_villages
        if normalize_name(village["census_village_name"]) in census_matches
    ]
    unmatched_villages = [
        village
        for village in census_villages
        if normalize_name(village["census_village_name"]) not in census_matches
    ]
    matched_census_population = sum(
        int(village["census_population_2011"]) for village in matched_villages
    )
    total_census_population = sum(
        int(village["census_population_2011"]) for village in census_villages
    )
    matched_point_rows = sum(habitation_counts[key] for key in census_matches)
    unmatched_point_rows = len(points_in_district) - matched_point_rows
    unmatched_unique_point_names = len(
        {
            normalize_name(name)
            for name in points_in_district["HAB_NAME"]
            if normalize_name(name) not in census_matches
        }
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    import csv

    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    point_rows = []
    for _, point in points_in_district.iterrows():
        key = normalize_name(point["HAB_NAME"])
        village = census_matches.get(key)
        point_rows.append(
            {
                "pmgsy_hab_id": point["HAB_ID"],
                "pmgsy_habitation_name": point["HAB_NAME"],
                "pmgsy_internal_district_id": point["DISTRICT_I"],
                "pmgsy_population_field": point["TOT_POPULA"],
                "longitude": point.geometry.x,
                "latitude": point.geometry.y,
                "census_village_name": village["census_village_name"] if village else "",
                "census_village_code": village["census_village_code"] if village else "",
                "crosswalk_status": (
                    "exact_normalized_name_match" if village else "unmatched"
                ),
            }
        )
    with POINT_OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(point_rows[0]))
        writer.writeheader()
        writer.writerows(point_rows)

    lines = [
        "# Alappuzha Census 2011 ↔ PMGSY habitation join",
        "",
        "## Sources and method",
        "",
        f"- Census: `{CENSUS_XLSX.relative_to(ROOT).as_posix()}`; [ORGI Census of India 2011 PCA-TV, Alappuzha](https://censusindia.gov.in/nada/index.php/catalog/6789) (district code 598).",
        f"- PMGSY: `{HABITATIONS_ZIP.relative_to(ROOT).as_posix()}`; [PMGSY GeoSadak Open Data](https://pmgsygeosadak.dord.gov.in/OpenData), Kerala habitation point layer; source IDs are PMGSY IDs, not Census village codes.",
        f"- Boundary: `{BOUNDARIES_GEOJSON.relative_to(ROOT).as_posix()}`; Alappuzha polygon selected by Census district code 598. Source: [geohacker/kerala](https://github.com/geohacker/kerala), based on [DataMeet district boundaries](https://github.com/datameet/maps), repository source last updated in 2018; boundary vintage may differ from the 2011 Census and PMGSY layer, so this is a spatial filter, not a legal boundary determination.",
        "- Spatial selection: valid WGS84 PMGSY point coordinates strictly within the Alappuzha polygon.",
        "- Name match: normalized English names (case, whitespace and punctuation normalized); qualifiers such as '(Part)' are retained. No fuzzy matching or forced assignment. Census village codes do not exist in the PMGSY habitation file.",
        "- A PMGSY habitation point is finer than a Census village; a village population is retained once per Census village, not duplicated across habitation points.",
        "",
        "## Counts",
        "",
        f"- Census rural village rows: {len(census_villages)}; population total: {total_census_population:,} (Census 2011).",
        f"- PMGSY habitation points spatially in boundary: {len(points_in_district):,}; invalid/out-of-range coordinates excluded before spatial selection: {invalid_coordinate_rows:,}.",
        f"- Census villages with an exact normalized-name match: {len(matched_villages)}/{len(census_villages)}; matched village population: {matched_census_population:,} ({matched_census_population / total_census_population:.1%} of Census rural population).",
        f"- Matched PMGSY habitation point records: {matched_point_rows:,}; these are not independent Census population observations.",
        f"- Unmatched Census villages: {len(census_villages) - len(matched_villages)}; unmatched Census population: {total_census_population - matched_census_population:,}.",
        f"- Unmatched PMGSY habitation point records: {unmatched_point_rows:,}; distinct normalized unmatched names: {unmatched_unique_point_names:,} (record-level detail is in the point crosswalk CSV).",
        "",
        "## Unmatched Census village records",
        "",
        *[
            f"- {village['census_village_name'].strip()} (Census village code {village['census_village_code']}): {int(village['census_population_2011']):,} people"
            for village in unmatched_villages
        ],
        "",
        "## Interpretation and limitations",
        "",
        f"This is a conservative **name-based crosswalk**, not a one-to-one population join. Census villages and PMGSY habitations are different geographic units. A matched Census population is a contextual village-level demand total, not population assigned to each PMGSY point. The {len(matched_villages)} matched village records account for {matched_census_population:,} people; do not sum that population once per matching habitation point. The {len(census_villages) - len(matched_villages)} unmatched villages and {total_census_population - matched_census_population:,} people remain visible in the CSV.",
        "",
        f"The PMGSY layer has {len(habitations):,} points for all Kerala. After spatial selection, {len(points_in_district):,} are inside the chosen polygon; {int((points_in_district['DISTRICT_I'] == 8).sum()):,} carry PMGSY internal district ID 8 and {len(points_in_district) - int((points_in_district['DISTRICT_I'] == 8).sum()):,} carry other internal IDs. Those 67 points have an internal district ID that disagrees with the spatial filter; both are preserved in the output rather than silently discarded. The PMGSY population field is a distinct source field and is not substituted for Census population.",
        "",
        f"- PMGSY point crosswalk rows: `{POINT_OUTPUT.relative_to(ROOT).as_posix()}`; this file includes all in-boundary PMGSY points and matched Census village codes, but intentionally does not repeat Census village population across points.",
        f"- Census village summary: `{OUTPUT.relative_to(ROOT).as_posix()}`.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(("\n".join(lines)).encode("ascii", "backslashreplace").decode("ascii"))
    print(
        f"\nWrote {OUTPUT.relative_to(ROOT)}, "
        f"{POINT_OUTPUT.relative_to(ROOT)} and {REPORT.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
