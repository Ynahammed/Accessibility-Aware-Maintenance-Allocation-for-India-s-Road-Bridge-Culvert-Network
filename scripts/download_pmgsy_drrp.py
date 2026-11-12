"""Download the PMGSY District Rural Road Plan network for one district (India only).

Source: Ministry of Rural Development DRRP layer published through Esri India's Living
Atlas, released under the Government Open Data License - India.

    Layer   : https://livingatlas.esri.in/server1/rest/services/PMGSY/IN_DRRP_Road_2021/MapServer/0
    Item    : https://www.arcgis.com/home/item.html?id=d621c3c1f3d54209baa61f82d2629629
    Citation: "Ministry of Rural Development, 2022. PMGSY Rural Connectivity Datasets,
               https://geosadak-pmgsy.nic.in/opendata/. Published under India's Government
               Open Data License: https://data.gov.in/government-open-data-license-india"

The layer carries road category, name and owner but no condition, traffic, inspection or
cost attributes; it is a district plan, not an audited as-built register.

Run: python scripts/download_pmgsy_drrp.py --district Alappuzha --state Kerala
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
QUERY_URL = (
    "https://livingatlas.esri.in/server1/rest/services/PMGSY/"
    "IN_DRRP_Road_2021/MapServer/0/query"
)
PAGE_SIZE = 2000


def count_features(where: str, timeout: int) -> int:
    response = requests.get(
        QUERY_URL,
        params={"where": where, "returnCountOnly": "true", "f": "json"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if "count" not in payload:
        raise RuntimeError(f"count query failed: {payload}")
    return int(payload["count"])


def download(where: str, expected: int, timeout: int) -> dict:
    """Page through the query result so maxRecordCount does not silently truncate it."""
    features: list[dict] = []
    offset = 0
    while offset < expected:
        response = requests.get(
            QUERY_URL,
            params={
                "where": where,
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
                "resultOffset": offset,
                "resultRecordCount": PAGE_SIZE,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        page = response.json().get("features", [])
        if not page:
            break
        features.extend(page)
        offset += len(page)
        print(f"  fetched {offset:,} of {expected:,}", flush=True)
    return {"type": "FeatureCollection", "features": features}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--district", default="Alappuzha")
    parser.add_argument("--state", default="Kerala")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "data/raw/pmgsy/alappuzha_drrp_roads.geojson")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    where = f"state='{args.state}' AND district='{args.district}'"
    expected = count_features(where, args.timeout)
    print(f"{args.district}, {args.state}: service reports {expected:,} road features")
    if expected == 0:
        print("No features matched; check the district/state spelling in the layer.", file=sys.stderr)
        return 1

    payload = download(where, expected, args.timeout)
    got = len(payload["features"])
    if got != expected:
        print(f"Refusing to write: downloaded {got:,} features but service counts {expected:,}.",
              file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"Wrote {got:,} features to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
