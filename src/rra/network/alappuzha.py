"""Allocation instance on a real district's layers (Alappuzha by default).

Every builder takes ``district`` (a slug from :mod:`rra.network.district_layers`); the
default keeps the original Alappuzha artifacts and call sites unchanged.

Topology, demand and destinations are **measured public layers**:

* road graph: Geofabrik/OSM extract clipped to the 2011 district boundary
  (``data/processed/<district>_network_join/roads_with_snapped_features.graphml``);
* demand: PMGSY GeoSadak habitation points *or* located Census 2011 villages,
  as two separate profiles that are never added together;
* destinations: mapped OSM hospitals.

Everything else is **assumed and labelled**:

* the 30 structures are the highest measured-loss *screening candidates* — geometric
  road/water intersections with ``verified_structure=False``, not an asset register;
* structure type follows the candidate class (an assumption, recorded per asset);
* condition is drawn uniformly from Fair/Poor/Severe, age from 5–40 years;
* outage days, repair effects and prices are the placeholder register defaults.

The screen is not the whole district: 3,859 candidates exist, 804 lie on a
habitation's hospital route, and the allocation problem is built on the 30 with the
largest measured solo loss (``crossing_solo_criticality.csv``). That keeps the mixed
integer program solvable on a 290k-node graph while saying plainly which 30 assets were
picked and why.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ..consequence.accessibility import AccessibilityModel
from .attach_assets import split_edge
from .district_layers import get_district
from .synthetic import District

ROOT = Path(__file__).resolve().parents[3]

#: Where the offline allocation build writes its plans. Kept here as well as in the app
#: registry because the build script imports it from this module.
ALLOCATION_DIR = ROOT / "data" / "processed" / "alappuzha_allocation"

DEMAND_PROFILES: tuple[str, ...] = ("pmgsy", "census")

#: Destination sets the accessibility measure can be run over. ``health`` is the hospital
#: tier the allocation uses; ``school`` adds colleges and kindergartens, i.e. every point
#: the join layer classified as educational. Markets are absent from the OSM extract
#: (no ``amenity=marketplace`` points), so they cannot be screened as a destination set.
DESTINATION_SETS: tuple[str, ...] = ("health", "school")


def _paths(district: str) -> dict[str, Path]:
    """Every processed layer the allocation instance reads for one district."""
    spec = get_district(district)
    join = spec.join_dir
    return {
        "join": join,
        "road_graphml": join / "roads_with_snapped_features.graphml",
        "pmgsy": join / "pmgsy_habitations_snapped.parquet",
        "census": join / "census_villages_snapped.parquet",
        "facilities": join / "osm_facilities_snapped.parquet",
        "candidates": join / "water_crossing_candidates.parquet",
        "criticality": spec.resilience_dir / "crossing_solo_criticality.csv",
    }

#: Candidate class -> structure type. **Assumption**: a road crossing a mapped linear
#: waterway or drain is screened as a culvert, a waterbody shoreline crossing as a minor
#: bridge. No inspection record supports either mapping.
TYPE_FROM_CANDIDATE_CLASS: dict[str, str] = {
    "linear_waterway_screen": "culvert",
    "drainage_screen": "culvert",
    "waterbody_shoreline_screen": "minor_bridge",
}

#: Ranking rules a portfolio can be built with. ``hospital_loss`` is the reported rule; the
#: others exist to test whether a result is a property of the *rule* that picked the assets.
#: Every one is stated in the output, because an unlabelled change of selection would make
#: the sensitivity analysis meaningless.
SELECTION_RULES: dict[str, str] = {
    "hospital_loss": (
        "30 highest measured solo-loss route-carrying crossing candidates "
        "(population_hours_lost measured on PMGSY habitations, in "
        "crossing_solo_criticality.csv), one candidate per road edge"
    ),
    "school_loss": (
        "30 highest measured solo-loss candidates under the school destination set "
        "(same graph, same candidates), one candidate per road edge"
    ),
    "bridge_tagged": (
        "30 highest measured hospital solo-loss candidates restricted to road edges that "
        "already carry an OSM bridge tag"
    ),
    "tag_first": (
        "30 candidates ranked on mapped evidence only: OSM bridge tag first, then snapping "
        "offset, then measured hospital loss — no consequence measure drives the order"
    ),
}

SELECTION_RULE = SELECTION_RULES["hospital_loss"]

ASSUMED = {
    "condition": "Uniform{1,2,3} = Fair/Poor/Severe per structure, drawn from the build seed",
    "age_years": "Uniform{5..40} per structure, drawn from the build seed",
    "structure_type": "mapped from the unverified candidate class (see TYPE_FROM_CANDIDATE_CLASS)",
    "outage_days": "placeholder register defaults by structure type",
    "repair_effects": "placeholder register defaults (no Indian inspection history)",
    "costs": "placeholder Schedule of Rates until a PWD reply is ingested",
    "rainfall": "lognormal monsoon ratio, mean 0.0 and sigma 0.4 on the daily loss model",
}

class LayersUnavailable(RuntimeError):
    """A required real-district layer is missing from the workspace."""


def layers_available(district: str = "alappuzha") -> bool:
    """True when every layer the instance needs for ``district`` is present."""
    return all(path.exists() for path in _paths(district).values() if path.suffix != "")


def _require_layers(district: str = "alappuzha") -> None:
    if layers_available(district):
        return
    spec = get_district(district)
    missing = [
        str(path.relative_to(ROOT))
        for key, path in _paths(district).items()
        if key != "join" and not path.exists()
    ]
    raise LayersUnavailable(
        f"real {spec.name} layers are missing: " + ", ".join(missing) +
        "; run scripts/clip_alappuzha_osm.py, scripts/join_alappuzha_census.py, "
        "scripts/attach_alappuzha_layers.py and scripts/alappuzha_resilience.py with "
        f"--district {spec.slug}"
    )


# --- road graph -------------------------------------------------------------------


@lru_cache(maxsize=4)
def road_graph(district: str = "alappuzha"):
    """The district road graph (junctions only), with numeric edge weights.

    The augmented GraphML carries snapped features as leaf nodes; allocation needs the
    road subgraph so a structure can *split* a road, not dangle off it. The graph is
    cached and never mutated: callers get a copy.
    """
    import networkx as nx

    _require_layers(district)
    raw = nx.read_graphml(_paths(district)["road_graphml"])
    graph = nx.Graph()
    for node, data in raw.nodes(data=True):
        if data.get("kind") != "junction":
            continue
        graph.add_node(node, pos=(float(data["x"]), float(data["y"])), kind="junction")
    for u, v, data in raw.edges(data=True):
        if u not in graph or v not in graph:
            continue
        graph.add_edge(
            u,
            v,
            length_m=float(data["length_m"]),
            travel_time_min=float(data["travel_time_min"]),
            road_class=str(data.get("highway") or "unclassified"),
            highway=str(data.get("highway") or "unclassified"),
        )
    return graph


def _projection_scale(coords: np.ndarray) -> np.ndarray:
    """Local metres-per-degree scale (Alappuzha is small enough that this is ample)."""
    lat0 = math.radians(float(coords[:, 1].mean()))
    return np.array([111_320.0 * math.cos(lat0), 110_574.0], dtype=float)


def _match_candidates_to_edges(graph, candidates: pd.DataFrame) -> pd.DataFrame:
    """Assign every candidate to its nearest road edge and position along it.

    Pure numpy/scipy: segment midpoint KD-tree for the shortlist, then exact
    point-to-segment distance. Offsets are reported so a bad match is visible.
    """
    from scipy.spatial import cKDTree

    nodes = list(graph.nodes)
    coords = np.array([graph.nodes[n]["pos"] for n in nodes], dtype=float)
    scale = _projection_scale(coords)
    projected = coords * scale

    index = {n: i for i, n in enumerate(nodes)}
    edges = np.array([(index[u], index[v]) for u, v in graph.edges()], dtype=np.int64)
    a = projected[edges[:, 0]]
    b = projected[edges[:, 1]]
    tree = cKDTree((a + b) / 2.0)

    points = np.c_[candidates.longitude.to_numpy(float), candidates.latitude.to_numpy(float)]
    points = points * scale
    k = int(min(8, len(edges)))
    neighbours = tree.query(points, k=k)[1]
    if k == 1:
        neighbours = neighbours[:, None]

    directions = b - a
    denom = (directions**2).sum(axis=1)
    edge_i = np.empty(len(candidates), dtype=np.int64)
    offset = np.empty(len(candidates), dtype=float)
    fraction = np.empty(len(candidates), dtype=float)
    for i in range(len(candidates)):
        candidates_i = neighbours[i]
        ap = points[i] - a[candidates_i]
        t = np.clip(
            (ap * directions[candidates_i]).sum(axis=1) / np.maximum(denom[candidates_i], 1e-12),
            0.0,
            1.0,
        )
        closest = a[candidates_i] + t[:, None] * directions[candidates_i]
        distance = np.linalg.norm(points[i] - closest, axis=1)
        best = int(np.argmin(distance))
        edge_i[i] = candidates_i[best]
        offset[i] = float(distance[best])
        fraction[i] = float(t[best])

    out = candidates.copy()
    out["edge_i"] = edge_i
    out["edge_u"] = [str(nodes[edges[j, 0]]) for j in edge_i]
    out["edge_v"] = [str(nodes[edges[j, 1]]) for j in edge_i]
    out["snap_offset_m"] = offset
    out["fraction"] = fraction
    return out


@lru_cache(maxsize=4)
def candidate_table(district: str = "alappuzha") -> pd.DataFrame:
    """Every water-crossing candidate for a district, each mapped to a road edge."""
    _require_layers(district)
    candidates = pd.read_parquet(_paths(district)["candidates"])
    candidates = candidates[
        candidates.longitude.notna() & candidates.latitude.notna()
    ].reset_index(drop=True)
    return _match_candidates_to_edges(road_graph(district), candidates)


def structure_portfolio(
    n_assets: int = 30,
    district: str = "alappuzha",
    ranking: str = "hospital_loss",
    scores: dict | None = None,
) -> tuple[dict, ...]:
    """The screened structure portfolio under one declared ranking rule.

    ``ranking`` selects how the candidates are ordered; ``scores`` supplies an external
    per-edge criticality for ``ranking='school_loss'`` (keyed by ``(edge_u, edge_v)``).
    Every alternative ranking returns the same number of structures on the same graph, so
    a downstream difference is attributable to the selection rule.
    """
    if ranking not in SELECTION_RULES:
        raise ValueError(f"unknown ranking {ranking!r}; expected one of {sorted(SELECTION_RULES)}")
    frozen = tuple(sorted((scores or {}).items()))
    return _portfolio(int(n_assets), district, ranking, frozen)


@lru_cache(maxsize=16)
def _portfolio(n_assets: int, district: str, ranking: str, frozen_scores: tuple):
    _require_layers(district)
    candidates = candidate_table(district).copy()
    criticality = pd.read_csv(_paths(district)["criticality"])
    criticality["edge_u"] = criticality.edge_u.astype(str)
    criticality["edge_v"] = criticality.edge_v.astype(str)

    # one candidate per road edge: the one closest to the road centreline
    best = candidates.sort_values(["edge_i", "snap_offset_m"]).drop_duplicates("edge_i")

    criticality = criticality.sort_values(
        ["population_hours_lost", "edge_u", "edge_v"], ascending=[False, True, True]
    ).drop_duplicates(["edge_u", "edge_v"])
    merged = criticality.merge(
        best, on=["edge_u", "edge_v"], how="inner", suffixes=("", "_candidate")
    )

    if ranking == "bridge_tagged":
        tagged = merged[merged.already_bridge_tagged.fillna(False).astype(bool)]
        if len(tagged) >= int(n_assets):
            merged = tagged
        order, ascending = ["population_hours_lost", "edge_u", "edge_v"], [False, True, True]
    elif ranking == "tag_first":
        merged = merged.assign(
            _tag_rank=(~merged.already_bridge_tagged.fillna(False).astype(bool)).astype(int)
        )
        order, ascending = ["_tag_rank", "snap_offset_m", "population_hours_lost"], [True, True, False]
    elif ranking == "school_loss":
        table = dict(frozen_scores)
        merged = merged.assign(
            _school_loss=[
                float(table.get((u, v), 0.0)) for u, v in zip(merged.edge_u, merged.edge_v)
            ]
        )
        order, ascending = ["_school_loss", "edge_u", "edge_v"], [False, True, True]
    else:
        order, ascending = ["population_hours_lost", "edge_u", "edge_v"], [False, True, True]

    merged = merged.sort_values(order, ascending=ascending).head(int(n_assets))

    records = []
    for rank, row in enumerate(merged.itertuples(index=False), start=1):
        candidate_class = str(row.candidate_class)
        records.append(
            {
                "asset_id": f"X{rank:03d}",
                "rank": rank,
                "edge_u": str(row.edge_u),
                "edge_v": str(row.edge_v),
                "fraction": float(np.clip(float(row.fraction), 0.05, 0.95)),
                "longitude": float(row.longitude),
                "latitude": float(row.latitude),
                "candidate_entity_id": str(row.entity_id),
                "candidate_class": candidate_class,
                "structure_type": TYPE_FROM_CANDIDATE_CLASS.get(candidate_class, "culvert"),
                "verified_structure": False,
                "road_name": None if pd.isna(row.road_name) else str(row.road_name),
                "road_osm_id": None if pd.isna(row.road_osm_id) else str(row.road_osm_id),
                "road_highway": None if pd.isna(row.road_highway) else str(row.road_highway),
                "waterway_type": None if pd.isna(row.waterway_type) else str(row.waterway_type),
                "already_bridge_tagged": bool(row.already_bridge_tagged),
                "snap_offset_m": float(row.snap_offset_m),
                "population_hours_lost": float(row.population_hours_lost),
                "origins_dependent": int(row.origins_dependent),
                "selection_ranking": ranking,
            }
        )
    return tuple(records)


# --- demand and destinations ------------------------------------------------------


def _attach_points(
    graph,
    frame: pd.DataFrame,
    *,
    prefix: str,
    kind: str,
    population_field: str | None = None,
    facility_type: str | None = None,
) -> dict:
    """Attach snapped points as leaf nodes with an on-foot connector edge.

    Reuses the snapping already recorded in the join layer (``nearest_node_id`` and
    ``nearest_node_distance_m``) so the instance is identical to the measured baseline.
    Returns ``node id -> population`` (empty values for facilities).
    """
    attached: dict = {}
    known = set(graph.nodes)
    for _, row in frame.iterrows():
        host = str(int(float(row.nearest_node_id)))
        if host not in known:
            continue
        distance = float(row.nearest_node_distance_m)
        if not math.isfinite(distance) or distance < 0:
            continue
        node = f"{prefix}:{row.entity_id}"
        attrs = {
            "pos": (float(row.longitude), float(row.latitude)),
            "kind": kind,
            "source_id": str(row.entity_id),
            "snapped_offset_m": distance,
        }
        if facility_type is not None:
            attrs["facility_type"] = facility_type
        graph.add_node(node, **attrs)
        graph.add_edge(
            node,
            host,
            length_m=distance,
            travel_time_min=(distance / 1000.0) / 5.0 * 60.0,
            road_class="connector",
            highway="connector",
        )
        population = 0.0
        if population_field is not None:
            value = float(row[population_field])
            population = value if math.isfinite(value) else 0.0
        attached[node] = population
    return attached


def _demand_table(demand: str, district: str = "alappuzha") -> tuple[pd.DataFrame, str, str]:
    paths = _paths(district)
    if demand == "pmgsy":
        frame = pd.read_parquet(paths["pmgsy"])
        frame = frame[frame.attached_to_network.fillna(False)].copy()
        frame = frame[frame.pmgsy_population_field.notna()]
        return frame, "pmgsy_population_field", "PMGSY habitation points"
    if demand == "census":
        frame = pd.read_parquet(paths["census"])
        frame = frame[frame.attached_to_network.fillna(False)].copy()
        frame = frame[frame.census_population_2011.notna()]
        return frame, "census_population_2011", "Census 2011 villages with a located point"
    raise ValueError(f"unknown demand profile {demand!r}; expected one of {DEMAND_PROFILES}")


def _facility_frame(district: str = "alappuzha", destination: str = "health") -> pd.DataFrame:
    frame = pd.read_parquet(_paths(district)["facilities"])
    frame = frame[frame.attached_to_network.fillna(False)]
    if destination == "health":
        frame = frame[(frame.facility_type == "health") & (frame.amenity == "hospital")]
    elif destination == "school":
        frame = frame[frame.facility_type == "school"]
    else:  # pragma: no cover - guarded by the caller
        raise ValueError(
            f"unknown destination set {destination!r}; expected one of {DESTINATION_SETS}"
        )
    return frame[frame.nearest_node_id.notna()]


def destination_access(
    district: District,
    destination: str,
    cap_minutes: float,
    weight: float,
) -> AccessibilityModel:
    """Accessibility model over one destination class on an *existing* instance.

    Only the destination set changes: the graph, habitations and structures are the ones
    the allocation instance already uses, so solo losses and the plan's benefit split stay
    comparable across destination sets. The new points are attached as leaf connectors,
    which cannot create a shortcut between existing nodes.
    """
    spec = get_district(district.metadata.get("district"))
    frame = _facility_frame(spec.slug, destination)
    nodes = _attach_points(
        district.graph,
        frame,
        prefix="facility",
        kind="facility",
        facility_type=destination,
    )
    return AccessibilityModel(
        district.graph,
        district.habitations,
        {destination: [node for node, _ in nodes.items()]},
        {destination: float(cap_minutes)},
        {destination: float(weight)},
        memoize=True,
    )


# --- the instance -----------------------------------------------------------------


def build_alappuzha_district(
    demand: str = "pmgsy",
    n_assets: int = 30,
    seed: int = 0,
    budget_crore: float = 0.5,
    crew_days: float = 150.0,
    district: str = "alappuzha",
    ranking: str = "hospital_loss",
    scores: dict | None = None,
) -> District:
    """Build the allocation instance on one district's real layers.

    ``demand`` selects **one** population universe (``pmgsy`` or ``census``); the two are
    never combined. Condition and age are assumed draws from ``seed``; outage, effects
    and prices are left to the register in ``rra.pipeline``. ``district`` picks the
    layer set (``alappuzha`` or ``pathanamthitta``). ``ranking`` selects the portfolio rule
    (see :data:`SELECTION_RULES`); the default reproduces the published portfolio exactly.
    """
    spec = get_district(district)
    selection_rule = SELECTION_RULES[ranking]
    _require_layers(district)
    graph = road_graph(district).copy()

    frame, population_field, demand_source = _demand_table(demand, district)
    habitations = _attach_points(
        graph,
        frame,
        prefix="habitation",
        kind="habitation",
        population_field=population_field,
    )

    facilities_frame = _facility_frame(district)
    health = _attach_points(
        graph,
        facilities_frame,
        prefix="facility",
        kind="facility",
        facility_type="health",
    )
    facilities = {"health": [node for node, _ in health.items()]}

    structures: list[tuple[str, str, str]] = []
    provenance: dict = {}
    condition: dict = {}
    age: dict = {}
    rng = np.random.default_rng(seed)
    for record in structure_portfolio(n_assets, district, ranking=ranking, scores=scores):
        asset_id = record["asset_id"]
        u, v = record["edge_u"], record["edge_v"]
        if not graph.has_edge(u, v):  # pragma: no cover - guarded by the measured join
            continue
        node = split_edge(
            graph,
            u,
            v,
            record["fraction"],
            asset_id,
            record["structure_type"],
        )
        structure_condition = int(rng.integers(1, 4))
        structure_age = int(rng.integers(5, 41))
        structures.append((asset_id, node, record["structure_type"]))
        condition[asset_id] = structure_condition
        age[asset_id] = structure_age
        provenance[asset_id] = {
            **record,
            "source_edge": [u, v],
            "selection_rule": selection_rule,
            "structure_type_basis": (
                "assumed from candidate class "
                f"{record['candidate_class']!r}; no inspection record"
            ),
            "condition": structure_condition,
            "condition_basis": f"assumed Uniform{{1,2,3}}, seed {seed}",
            "age": structure_age,
            "age_basis": f"assumed Uniform{{5..40}}, seed {seed}",
        }

    instance = District(
        graph=graph,
        habitations=habitations,
        facilities=facilities,
        structures=structures,
        budget_crore=float(budget_crore),
        crew_days=float(crew_days),
        asset_provenance=provenance,
        condition_by_asset=condition,
        age_by_asset=age,
        memoize_accessibility=True,
        demand_profile=demand,
    )
    census_total = census_matched = 0
    if spec.census_join_csv.exists():
        census_rows = pd.read_csv(spec.census_join_csv)
        census_total = int(len(census_rows))
        census_matched = int(
            (census_rows.get("match_status") == "matched_exact_normalized_name").sum()
        )
    sources = {
        "road_graph": (
            "Geofabrik/OSM extract clipped to the 2011 "
            f"{spec.name} boundary; {graph.number_of_nodes():,} junction nodes and "
            f"{graph.number_of_edges():,} road edges"
        ),
        "demand_pmgsy": (
            "PMGSY GeoSadak habitation points "
            f"({sum(habitations.values()):,.0f} in the source population field; "
            "not Census population)"
        ),
        "demand_census": (
            "Census 2011 village totals at exact-name matched PMGSY-weighted centroids "
            f"({census_matched} of {census_total} villages have a defensible point)"
        ),
        "destinations": (
            f"{len(health)} OSM ``amenity=hospital`` points attached within 500 m"
        ),
        "structures": (
            f"{len(candidate_table(district)):,} unverified road/water intersection "
            f"candidates; the allocation uses the {len(structures)} highest measured "
            "solo-loss candidates"
        ),
    }
    instance.metadata = {
        "district": spec.slug,
        "district_name": spec.name,
        "demand_profile": demand,
        "demand_source": demand_source,
        "selection_rule": selection_rule,
        "selection_ranking": ranking,
        "assumed": dict(ASSUMED),
        "sources": sources,
    }
    return instance


def instance_metadata(
    demand: str = "pmgsy",
    n_assets: int = 30,
    seed: int = 0,
    budget_crore: float = 0.5,
    crew_days: float = 150.0,
    district: str = "alappuzha",
    ranking: str = "hospital_loss",
    scores: dict | None = None,
) -> dict:
    """Descriptive metadata and per-asset provenance, without keeping the graph.

    Used by the registry's summary view and written by
    ``scripts/build_alappuzha_allocation.py``; it builds the instance once so the counts
    and the provenance come from the same objects the planner uses.
    """
    spec = get_district(district)
    instance = build_alappuzha_district(
        demand=demand,
        n_assets=n_assets,
        seed=seed,
        budget_crore=budget_crore,
        crew_days=crew_days,
        district=district,
        ranking=ranking,
        scores=scores,
    )
    assets = [
        instance.asset_provenance[asset_id]
        for asset_id, _, _ in instance.structures
        if asset_id in instance.asset_provenance
    ]
    population = float(sum(instance.habitations.values()))
    road = road_graph(district)
    return {
        "district_id": f"{spec.slug}-network-{demand}",
        "district_name": spec.name,
        "demand_profile": demand,
        "seed": int(seed),
        "budget_crore": float(budget_crore),
        "crew_days": float(crew_days),
        "counts": {
            "n_nodes": road.number_of_nodes(),
            "n_edges": road.number_of_edges(),
            "n_instance_nodes": instance.graph.number_of_nodes(),
            "n_instance_edges": instance.graph.number_of_edges(),
            "n_habitations": len(instance.habitations),
            "n_structures": len(instance.structures),
            "n_health_facilities": len(instance.facilities.get("health", [])),
            "demand_population": population,
        },
        "selection": {
            "rule": instance.metadata.get("selection_rule", SELECTION_RULE),
            "ranking": ranking,
            "ranking_basis": "PMGSY habitation population; the same portfolio is reused "
            "for the Census profile so both demand views share one asset set",
            "n_assets": len(instance.structures),
            "n_candidates_screened": int(len(candidate_table(district))),
            "n_route_carrying_edges": int(len(pd.read_csv(_paths(district)["criticality"]))),
        },
        "assumed": dict(ASSUMED),
        "sources": dict(instance.metadata.get("sources", {})),
        "note": _instance_note(demand, district),
        "assets": assets,
    }


def _instance_note(demand: str, district: str = "alappuzha") -> str:
    spec = get_district(district)
    population = "PMGSY habitation population field" if demand == "pmgsy" else "Census 2011 village totals"
    extra = (
        ""
        if demand == "pmgsy"
        else (
            " The portfolio is ranked on PMGSY-population loss and held fixed here so both "
            "demand views share one asset set; Census losses did not select it."
        )
    )
    return (
        f"Real {spec.name} road graph with real demand (" + population + ") and mapped OSM "
        "hospital destinations. The 30 structures are unverified road/water screening "
        "candidates selected by measured solo loss, not an asset register; condition, age, "
        "outage and cost are assumed. Findings are a planning exercise, not observed "
        "condition or a spending recommendation." + extra
    )
