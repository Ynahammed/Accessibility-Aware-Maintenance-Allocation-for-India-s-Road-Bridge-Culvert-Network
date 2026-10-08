"""QA a downloaded OSM network (plan 5.1 output: qa_report.md).

    python scripts/qa_osm_network.py data/raw/osm/roads.graphml

Reports component structure and OSM bridge/culvert tag coverage — the plan's high-risk
"tags too sparse" check, measured rather than assumed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rra.ingest.osm import load_osm_graphml, tag_coverage  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/raw/osm/roads.graphml"
    g = load_osm_graphml(path)

    comps = list(nx.connected_components(g))
    n_nodes = g.number_of_nodes()
    largest = max((len(c) for c in comps), default=0)
    cov = tag_coverage(g)

    lines = [
        f"# OSM network QA — {path.name}",
        "",
        f"- nodes: {n_nodes}",
        f"- edges: {cov['n_edges']}",
        f"- connected components: {len(comps)}",
        f"- share in largest component: {largest / n_nodes:.3f}" if n_nodes else "- share: n/a",
        f"- edges tagged as bridge: {cov['n_bridges']} ({cov['bridge_share']:.4%})",
        f"- edges tagged as culvert: {cov['n_culverts']} ({cov['culvert_share']:.4%})",
        "",
        "OSM bridge/culvert tags are sparse; the plan's mitigation is to infer crossings",
        "where roads meet water bodies, or to use PMGSY structures where present.",
        "",
    ]
    text = "\n".join(lines)
    out_dir = ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "osm_qa.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"(wrote {out_dir / 'osm_qa.md'})")


if __name__ == "__main__":
    main()
