"""India-only Alappuzha baseline: settlement access to mapped OSM facilities.

Uses the district road graph and snapped layers produced by
``scripts/attach_alappuzha_layers.py``. Census and PMGSY population measures are
kept separate. Times are free-flow model estimates, not observed journeys.

Run: python scripts/alappuzha_access_baseline.py
"""
from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
JOIN = ROOT / "data/processed/alappuzha_network_join"
OUT = ROOT / "data/processed/alappuzha_access_baseline"
THRESHOLDS_MIN = (15, 30, 60)
# Destination tiers. "health_any" bundles clinics and doctors' offices with hospitals and is
# easy to satisfy in a densely mapped district, so the hospital-only tier is reported too.
FACILITY_TYPES = ("hospital", "health_any", "school")
DESTINATION_LABELS = {
    "hospital": "hospital (amenity=hospital)",
    "health_any": "health point (hospital, clinic or doctors' office)",
    "school": "school (school, college, kindergarten)",
}


def read_layer(name: str, columns: list[str]) -> pd.DataFrame:
    frame = pd.read_parquet(JOIN / name, columns=columns)
    return frame


def population_summary(rows: pd.DataFrame) -> dict:
    population = pd.to_numeric(rows["population_value"], errors="coerce").fillna(0)
    has_coordinate = rows["snap_status"].ne("no_coordinate")
    attached = rows["attached_to_network"].fillna(False).astype(bool)
    summary = {
        "origin_records": int(len(rows)),
        "source_population_total": int(population.sum()),
        "coordinate_records": int(has_coordinate.sum()),
        "coordinate_population": int(population[has_coordinate].sum()),
        "no_coordinate_records": int((~has_coordinate).sum()),
        "no_coordinate_population": int(population[~has_coordinate].sum()),
        "network_attached_records": int(attached.sum()),
        "network_attached_population": int(population[attached].sum()),
        "coordinate_but_not_attached_records": int((has_coordinate & ~attached).sum()),
        "coordinate_but_not_attached_population": int(population[has_coordinate & ~attached].sum()),
    }
    for destination in FACILITY_TYPES:
        col = f"minutes_to_{destination}"
        reachable = pd.to_numeric(rows[col], errors="coerce")
        has_route = reachable.notna()
        no_route_attached = attached & ~has_route
        summary[f"attached_but_no_route_to_{destination}_records"] = int(no_route_attached.sum())
        summary[f"attached_but_no_route_to_{destination}_population"] = int(population[no_route_attached].sum())
        valid = reachable[has_route]
        summary[f"routed_{destination}_median_minutes"] = (
            float(valid.median()) if not valid.empty else None
        )
        for threshold in THRESHOLDS_MIN:
            within = reachable.le(threshold).fillna(False)
            covered = int(population[within].sum())
            summary[f"{destination}_within_{threshold}min_population"] = covered
            summary[f"{destination}_within_{threshold}min_records"] = int(within.sum())
            for denominator_name, mask in (
                ("source_population", pd.Series(True, index=rows.index)),
                ("coordinate_population", has_coordinate),
                ("network_attached_population", attached),
            ):
                denominator = int(population[mask].sum())
                summary[f"{destination}_within_{threshold}min_share_of_{denominator_name}"] = (
                    int(population[within & mask].sum()) / denominator if denominator else None
                )
    return summary


def main() -> None:
    graph = nx.read_graphml(JOIN / "roads_with_snapped_features.graphml")
    # Convert serialized GraphML string weights to numeric for shortest paths.
    for _, _, data in graph.edges(data=True):
        data["travel_time_min"] = float(data["travel_time_min"])

    nodes_by_source = {
        data["source_id"]: node
        for node, data in graph.nodes(data=True)
        if data.get("source_id") is not None
    }
    facilities = read_layer(
        "osm_facilities_snapped.parquet",
        ["entity_id", "facility_type", "amenity", "attached_to_network"],
    )
    members = {
        "hospital": facilities.facility_type.eq("health") & facilities.amenity.eq("hospital"),
        "health_any": facilities.facility_type.eq("health"),
        "school": facilities.facility_type.eq("school"),
    }
    target_nodes = {
        kind: [
            nodes_by_source[row.entity_id]
            for row in facilities.loc[members[kind]].itertuples()
            if bool(row.attached_to_network) and row.entity_id in nodes_by_source
        ]
        for kind in FACILITY_TYPES
    }
    nearest_minutes = {
        kind: nx.multi_source_dijkstra_path_length(
            graph, sources, weight="travel_time_min"
        )
        for kind, sources in target_nodes.items()
    }

    specifications = [
        (
            "PMGSY habitation population field",
            "pmgsy_habitations_snapped.parquet",
            ["entity_id", "habitation_name", "longitude", "latitude", "pmgsy_population_field", "snap_status", "attached_to_network"],
            "pmgsy_population_field",
            "pmgsy_population_field",
        ),
        (
            "Census 2011 village population",
            "census_villages_snapped.parquet",
            ["entity_id", "census_village_code", "census_village_name", "longitude", "latitude", "census_population_2011", "snap_status", "attached_to_network"],
            "census_population_2011",
            "census_population_2011",
        ),
    ]
    output_frames = []
    summaries = {}
    for population_source, filename, columns, population_column, output_population_column in specifications:
        frame = read_layer(filename, columns)
        frame["population_source"] = population_source
        frame["population_value"] = pd.to_numeric(frame[population_column], errors="coerce")
        frame["population_unit_definition"] = population_source
        for kind in FACILITY_TYPES:
            values = []
            lookup = nearest_minutes[kind]
            for row in frame.itertuples():
                node = nodes_by_source.get(row.entity_id) if bool(row.attached_to_network) else None
                values.append(float(lookup[node]) if node in lookup else None)
            frame[f"minutes_to_{kind}"] = values
        summaries[population_source] = population_summary(frame)
        output_frames.append(frame.drop(columns=[population_column], errors="ignore"))

    OUT.mkdir(parents=True, exist_ok=True)
    combined = pd.concat(output_frames, ignore_index=True, sort=False)
    combined.to_csv(OUT / "origin_access.csv", index=False)
    report = {
        "title": "Alappuzha network access baseline",
        "source_scope": "Indian Census 2011, PMGSY GeoSadak, Alappuzha OSM and district road graph",
        "network_nodes": graph.number_of_nodes(),
        "network_edges": graph.number_of_edges(),
        "mapped_facilities": {kind: len(target_nodes[kind]) for kind in FACILITY_TYPES},
        "thresholds_minutes": list(THRESHOLDS_MIN),
        "speed_model": "OSM highway-class speeds in graph; 5 km/h straight-line snap connectors",
        "population_views": summaries,
        "caveats": [
            "PMGSY TOT_POPULA source field is not assumed to be Census 2011 population; PMGSY values are not recency-adjusted.",
            "Census and PMGSY populations are separate denominators and must not be added.",
            "Only exact-name matched Census villages have approximate weighted-centroid coordinates; unmatched villages remain in the output with null access times.",
            "OSM facilities are volunteered mapping, not a complete or authoritative facility register. Dense volunteered points make the 'any mapped health point' tier easy to satisfy; both tiers are reported.",
            "Times are free-flow estimates from assumed highway-class speeds; they do not include congestion, flood disruption, road condition, seasonal passability, or service capacity.",
            "This access baseline is not an asset-condition assessment or maintenance recommendation.",
        ],
    }
    (OUT / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Alappuzha network access baseline",
        "",
        "India-only descriptive analysis using Census 2011, PMGSY GeoSadak, the district OSM clip, and its road graph.",
        "",
        f"- Network: {graph.number_of_nodes():,} nodes and {graph.number_of_edges():,} edges.",
        "- Attached OSM destinations: " + "; ".join(
            f"{len(target_nodes[kind]):,} {kind}" for kind in FACILITY_TYPES
        ) + ".",
        "- Access is estimated as nearest network travel time using OSM highway-class speeds and 5 km/h snap connectors.",
        "- Coverage bands: 15, 30, and 60 minutes; summaries are population-weighted and shown separately for each source.",
        "",
    ]
    for source, summary in summaries.items():
        lines += [f"## {source}", "", f"- Origin records: {summary['origin_records']:,}; source population total: {summary['source_population_total']:,}.", f"- Located origins: {summary['coordinate_records']:,} ({summary['coordinate_population']:,}); missing coordinates: {summary['no_coordinate_records']:,} ({summary['no_coordinate_population']:,}).", f"- Network-attached origins: {summary['network_attached_records']:,} ({summary['network_attached_population']:,}); coordinate-bearing origins outside the 500 m snap limit: {summary['coordinate_but_not_attached_records']:,} ({summary['coordinate_but_not_attached_population']:,}).", ""]
        for destination in FACILITY_TYPES:
            lines.append(f"### Nearest mapped {DESTINATION_LABELS[destination]}")
            lines.append("")
            lines.append(f"- Attached origins with no route to a mapped destination: {summary[f'attached_but_no_route_to_{destination}_records']:,} ({summary[f'attached_but_no_route_to_{destination}_population']:,}).")
            lines.append(f"- Median among routed origins: {summary[f'routed_{destination}_median_minutes']:.1f} min." if summary[f"routed_{destination}_median_minutes"] is not None else "- No routed origins.")
            for threshold in THRESHOLDS_MIN:
                for denominator_name, label in (("source_population", "all source population"), ("coordinate_population", "population with locations"), ("network_attached_population", "population attached to network")):
                    share = summary[f"{destination}_within_{threshold}min_share_of_{denominator_name}"]
                    pct = "n/a" if share is None else f"{share:.1%}"
                    lines.append(f"- Within {threshold} min: {pct} of {label}.")
            lines.append("")
    lines += [
        "## Interpretation limits",
        "",
        "PMGSY population-field totals and Census 2011 totals are separate sources; do not sum them. The Census locations are approximate weighted centroids and 30 unmatched villages have null coordinates. OSM health/school mapping is volunteered and incomplete. Travel times use free-flow class-speed assumptions and do not include congestion, flood closure, road condition, or facility capacity. This is not a maintenance recommendation.",
        "",
        "Detailed per-origin results are in `origin_access.csv`; machine-readable summaries are in `summary.json`.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
