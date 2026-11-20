"""The real Alappuzha allocation instance.

Skipped when the public layers are not present. These tests pin the parts that make the
instance honest: the real graph counts, the screened portfolio and its labels, the two
separate demand universes, and the split that makes a structure failure cut the road.
"""

import time

import pytest

from rra.app.districts import (
    allocation_artifact,
    allocation_metadata,
    get_spec,
    summarize,
)
from rra.app.planning import _persisted_plan, build_plan
from rra.app.register import live_register
from rra.network import alappuzha as az

pytestmark = pytest.mark.skipif(
    not az.layers_available(), reason="real Alappuzha layers are not present"
)


def test_real_graph_is_the_district_graph():
    graph = az.road_graph()
    assert graph.number_of_nodes() == 290_041
    assert graph.number_of_edges() == 299_430
    # edge weights are numeric, so the consequence model can route
    u, v = next(iter(graph.edges()))
    assert isinstance(graph.edges[u, v]["travel_time_min"], float)


def test_portfolio_is_a_screened_labelled_set():
    portfolio = az.structure_portfolio()
    assert len(portfolio) == 30
    assert len({(r["edge_u"], r["edge_v"]) for r in portfolio}) == 30
    assert [r["rank"] for r in portfolio] == list(range(1, 31))
    losses = [r["population_hours_lost"] for r in portfolio]
    assert losses == sorted(losses, reverse=True)
    for record in portfolio:
        assert record["verified_structure"] is False
        assert record["structure_type"] in {"culvert", "minor_bridge"}
        assert 0.0 < record["fraction"] < 1.0
        assert record["candidate_entity_id"].startswith("crossing:")
        assert az.SELECTION_RULE.startswith("30 highest")


def test_demand_profiles_are_separate_universes():
    pmgsy, pmgsy_field, _ = az._demand_table("pmgsy")
    census, census_field, _ = az._demand_table("census")
    assert pmgsy_field == "pmgsy_population_field"
    assert census_field == "census_population_2011"
    assert len(pmgsy) == 1_978
    assert int(pmgsy[pmgsy_field].sum()) == 2_165_691
    assert len(census) == 22
    assert int(census[census_field].sum()) == 437_682
    # two different populations; neither is the other's denominator
    assert int(pmgsy[pmgsy_field].sum()) != int(census[census_field].sum())


def test_instance_uses_one_demand_profile_and_assumed_condition():
    district = az.build_alappuzha_district("pmgsy", n_assets=3, seed=0)
    assert len(district.habitations) == 1_978
    assert sum(district.habitations.values()) == pytest.approx(2_165_691.0)
    assert len(district.facilities["health"]) == 309
    assert len(district.structures) == 3
    assert district.demand_profile == "pmgsy"
    assert district.memoize_accessibility is True

    for asset_id, node, structure_type in district.structures:
        assert district.graph.nodes[node]["kind"] == "structure"
        assert district.graph.degree(node) == 2
        assert 1 <= district.condition_by_asset[asset_id] <= 3
        assert 5 <= district.age_by_asset[asset_id] <= 40
        provenance = district.asset_provenance[asset_id]
        assert provenance["verified_structure"] is False
        assert provenance["condition_basis"].startswith("assumed")
        assert provenance["age_basis"].startswith("assumed")
        # the source road edge was split, so a structure failure really cuts the route
        u, v = provenance["source_edge"]
        assert not district.graph.has_edge(u, v)


def test_real_specs_use_the_additive_policy():
    for demand in ("pmgsy", "census"):
        spec = get_spec(f"alappuzha-network-{demand}")
        assert spec.status == "ready"
        assert spec.provenance == "real-alappuzha"
        assert spec.demand == demand
        assert spec.planning_policy == "additive_milp"


def test_matching_request_is_served_from_the_persisted_plan():
    if allocation_artifact("pmgsy_plan.json") is None:
        pytest.skip("run scripts/build_alappuzha_allocation.py to persist the plan")
    started = time.monotonic()
    plan = build_plan(
        "alappuzha-network-pmgsy",
        budget_crore=0.5,
        crew_days=150.0,
        seed=0,
        scenarios=8,
        years=1,
    )
    elapsed = time.monotonic() - started
    assert plan["cached"] is True
    assert plan["cached_from"].endswith("pmgsy_plan.json")
    assert plan["policy"] == "additive_milp"
    assert plan["recommendations"]
    assert elapsed < 5.0  # no graph build or accessibility solve on this path


def test_other_parameters_do_not_use_the_persisted_plan():
    if allocation_artifact("pmgsy_plan.json") is None:
        pytest.skip("run scripts/build_alappuzha_allocation.py to persist the plan")
    spec = get_spec("alappuzha-network-pmgsy")
    live = live_register()
    assert _persisted_plan(spec, live, 0.55, 150.0, 0, 8, 1) is None
    assert _persisted_plan(spec, live, 0.5, 120.0, 0, 8, 1) is None
    assert _persisted_plan(spec, live, 0.5, 150.0, 1, 8, 1) is None
    assert _persisted_plan(get_spec("synth-generic"), live, 0.6, 400.0, 0, 8, 1) is None


def test_summary_uses_persisted_metadata_when_present():
    if allocation_metadata("pmgsy") is None:
        pytest.skip("run scripts/build_alappuzha_allocation.py to persist metadata")
    summary = summarize("alappuzha-network-pmgsy")
    assert summary["instance_built"] is True
    assert summary["n_structures"] == 30
    assert summary["n_habitations"] == 1_978
    assert "Fair/Poor/Severe" in summary["assumed"]["condition"]
