"""Build a real district network from downloaded OSM layers (plan 5.1).

    python scripts/build_real_district.py --osm data/raw/osm --out data/processed

Consumes whatever layers are present and reports QA honestly:

* ``roads.graphml`` (always, from the OSM downloader) -> routable graph
* ``water.parquet``   (optional) -> road-over-water crossing inference, recovering the
  structures that OSM leaves untagged (culvert coverage was 0% in the test district)
* ``places.parquet`` / ``facilities.parquet`` (optional) -> habitations and health/school
  destinations, which the accessibility model needs

Writes ``<out>/real_district_qa.md`` and ``<out>/structures.parquet``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rra.ingest import osm  # noqa: E402


def load_if_present(path: Path):
    if path.exists():
        import geopandas as gpd

        return gpd.read_parquet(path)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--osm", default="data/raw/osm")
    ap.add_argument("--out", default="data/processed")
    args = ap.parse_args()

    osm_dir = ROOT / args.osm
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    roads_path = osm_dir / "roads.graphml"
    g = osm.load_osm_graphml(roads_path)
    cov = osm.tag_coverage(g)
    comps = list(nx.connected_components(g))
    n_nodes = g.number_of_nodes()
    largest = max((len(c) for c in comps), default=0)

    # --- structures: tagged bridges + inferred crossings -------------------------------
    tagged = [(u, v) for u, v, d in g.edges(data=True) if d.get("is_bridge") or d.get("is_culvert")]
    water = load_if_present(osm_dir / "water.parquet")
    inferred: list = []
    if water is not None:
        import osmnx as ox
        from shapely.geometry import mapping  # noqa: F401

        graph = ox.load_graphml(roads_path)
        _, edges_gdf = ox.graph_to_gdfs(graph)
        inferred = osm.infer_crossings(edges_gdf.reset_index(), water)

    # --- habitation / facility layers (may be absent) ----------------------------------
    places = load_if_present(osm_dir / "places.parquet")
    facilities = load_if_present(osm_dir / "facilities.parquet")
    habitations = osm.extract_habitations(places) if places is not None else []
    fac = osm.extract_facilities(facilities) if facilities is not None else {"health": [], "school": []}

    lines = [
        "# Real district network QA",
        "",
        f"- nodes: {n_nodes}",
        f"- edges: {cov['n_edges']}",
        f"- connected components: {len(comps)}",
        f"- share in largest component: {largest / n_nodes:.3f}" if n_nodes else "- share: n/a",
        "",
        "## Structures",
        f"- edges tagged bridge/culvert: {len(tagged)} "
        f"({cov['n_bridges']} bridge, {cov['n_culverts']} culvert)",
    ]
    if water is None:
        lines.append("- water layer: **missing** -> crossing inference skipped "
                     "(Overpass feature fetch blocked here; retry on a network with access)")
    else:
        lines.append(f"- inferred road-over-water crossings: {len(inferred)}")
        lines.append(f"- total structure candidates: {len(tagged) + len(inferred)}")
    lines += [
        "",
        "## Habitations and facilities",
        f"- habitation points (OSM place): {len(habitations)}",
        f"- health facilities: {len(fac['health'])}, schools: {len(fac['school'])}",
    ]
    if not habitations or not fac["health"]:
        lines.append("- **accessibility loss cannot be computed yet**: needs both habitation and "
                     "health-facility layers (PMGSY is blocked here; OSM feature fetch also failed)")
    lines += [
        "",
        "This is the plan's week-1 exit test in progress: one command that reconstructs a "
        "district's network from raw data. The road graph reproduces; the structure and "
        "habitation layers depend on the blocked sources.",
        "",
    ]
    text = "\n".join(lines)
    (out_dir / "real_district_qa.md").write_text(text, encoding="utf-8")

    import pandas as pd

    pd.DataFrame(
        {"edge_u": [u for u, _ in tagged], "edge_v": [v for _, v in tagged], "source": "tagged"}
    ).to_parquet(out_dir / "structures.parquet")

    print(text)
    print(f"(wrote {out_dir / 'real_district_qa.md'} and structures.parquet)")


if __name__ == "__main__":
    main()
