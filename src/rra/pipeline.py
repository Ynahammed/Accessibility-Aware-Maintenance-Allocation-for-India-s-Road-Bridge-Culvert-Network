"""Pipeline conveniences: district + register -> models and world.

Keeps experiments thin and reproducible: the same builders are used by tests, the E3
experiment and (later) the API/dashboard, so every number traces to one code path.
"""

from __future__ import annotations

import numpy as np

from rra.assumptions import AssumptionRegister
from rra.consequence.accessibility import AccessibilityModel
from rra.cost.sor import ScheduleOfRates
from rra.deterioration import markov
from rra.fragility.fragility import FragilityParams
from rra.network.synthetic import District
from rra.simulator.state import Asset, World


def accessibility_model(district: District, register: AssumptionRegister) -> AccessibilityModel:
    caps = {
        "health": register["travel_time_cap_health"].default,
        "school": register["travel_time_cap_school"].default,
    }
    weights = {
        "health": register["facility_weight_health"].default,
        "school": register["facility_weight_school"].default,
    }
    return AccessibilityModel(
        district.graph, district.habitations, district.facilities, caps, weights
    )


def default_transition(seed: int = 0, acceleration: float = 1.0) -> np.ndarray:
    """A worsening-biased transition matrix (stands in for an NBI-fitted M0).

    ``acceleration`` multiplies the *worsening* transition counts only, implementing the
    register's Indian-vs-NBI acceleration axis.
    """
    counts = np.zeros((4, 4))
    for i in range(3):
        counts[i, i + 1] = 6.0 * acceleration
        counts[i, i] = 3.0
    counts[3, 3] = 10.0
    counts[2, 3] = 5.0 * acceleration
    return markov.fit_transition_matrix(counts)


def outage_days_by_type(register: AssumptionRegister) -> dict:
    return {
        "culvert": register["outage_mean_days_culvert"].default,
        "minor_bridge": register["outage_mean_days_minor_bridge"].default,
        "major_bridge": register["outage_mean_days_major_bridge"].default,
        "road_segment": register["outage_mean_days_culvert"].default,
    }


def build_models(district: District, register: AssumptionRegister, seed: int = 0):
    from rra.simulator.step import SimModels

    outage_by_type = outage_days_by_type(register)
    outage = {aid: outage_by_type[t] for aid, _, t in district.structures}
    return SimModels(
        acc=accessibility_model(district, register),
        transition=default_transition(seed, register["deterioration_acceleration"].default),
        fragility=FragilityParams.from_register(register),
        sor=ScheduleOfRates(),
        outage_days=outage,
        premium=register["emergency_premium"].default,
    )


def build_world(district: District, register: AssumptionRegister, seed: int = 0) -> World:
    rng = np.random.default_rng(seed)
    assets = {}
    for asset_id, node, s_type in district.structures:
        assets[asset_id] = Asset(
            asset_id=asset_id,
            structure_type=s_type,
            node=node,
            age=int(rng.integers(0, 40)),
            condition=int(rng.integers(0, 3)),
        )
    return World(
        assets=assets,
        budget_crore=district.budget_crore,
        crew_days=district.crew_days,
    )
