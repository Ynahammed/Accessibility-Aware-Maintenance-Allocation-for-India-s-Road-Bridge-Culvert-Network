"""One simulated year and the paired-scenario harness (plan section 5.6).

A year proceeds exactly as the plan states:

1. apply the policy's interventions within budget;
2. deteriorate each structure with the fitted transition model;
3. draw a monsoon scenario;
4. draw failures with **common random numbers**;
5. compute L(F), the outage cost and the emergency repair cost; log everything.

All policies are run against the **same** ``ScenarioSet`` (same rain fields, same
deterioration uniforms, same failure uniforms), so policy differences are paired.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from rra.consequence.accessibility import AccessibilityModel
from rra.cost.interventions import Intervention, apply_condition
from rra.cost.sor import ScheduleOfRates
from rra.deterioration.markov import N_STATES
from rra.fragility.fragility import FragilityParams, failure_probability
from rra.simulator.state import Asset, World

DEFAULT_OUTAGE_DAYS: dict[str, float] = {
    "culvert": 10.0,
    "minor_bridge": 30.0,
    "major_bridge": 120.0,
    "road_segment": 7.0,
}


@dataclass
class ScenarioSet:
    """Pre-drawn, policy-independent randomness. Shape of each list is [scenario][year]."""

    n: int
    years: int
    asset_ids: list
    rain: list  # [s][y] -> np.ndarray (n_assets,) rainfall ratio
    det_u: list  # [s][y] -> np.ndarray uniform for transition sampling
    fail_u: list  # [s][y] -> np.ndarray uniform for failure sampling

    def rain_for(self, s: int, y: int) -> dict:
        return dict(zip(self.asset_ids, self.rain[s][y]))


def make_scenarios(
    asset_ids: list,
    years: int,
    n: int,
    rng: np.random.Generator | int,
    rain: np.ndarray | None = None,
) -> ScenarioSet:
    """Draw a scenario set. ``rain`` may supply (n, years, n_assets) ratios."""
    if isinstance(rng, (int, np.integer)):
        rng = np.random.default_rng(int(rng))
    n_assets = len(asset_ids)
    if rain is not None:
        rain = np.asarray(rain, dtype=float)
        if rain.shape != (n, years, n_assets):
            raise ValueError(f"rain must be {(n, years, n_assets)}, got {rain.shape}")
    rain_list = [
        [rain[s, y] if rain is not None else
         np.exp(rng.normal(0.0, 0.4, size=n_assets))  # lognormal monsoon ratio
         for y in range(years)]
        for s in range(n)
    ]
    det_u = [[rng.random(n_assets) for _ in range(years)] for _ in range(n)]
    fail_u = [[rng.random(n_assets) for _ in range(years)] for _ in range(n)]
    return ScenarioSet(n, years, list(asset_ids), rain_list, det_u, fail_u)


@dataclass
class SimModels:
    acc: AccessibilityModel
    transition: np.ndarray  # (4, 4) row-stochastic
    fragility: FragilityParams
    sor: ScheduleOfRates
    outage_days: dict = field(default_factory=dict)  # asset_id -> days (else by type)
    premium: float = 1.8

    def outage(self, asset: Asset) -> float:
        return float(
            self.outage_days.get(asset.asset_id, DEFAULT_OUTAGE_DAYS.get(asset.structure_type, 30.0))
        )


@dataclass
class PolicyOutcome:
    name: str
    person_days: np.ndarray  # (n_scenarios,) total access lost
    planned: np.ndarray  # (n_scenarios,) planned intervention spend
    emergency: np.ndarray  # (n_scenarios,) emergency restoration spend

    @property
    def spend(self) -> np.ndarray:
        return self.planned + self.emergency


def _sample_next_state(condition: int, P: np.ndarray, u: float) -> int:
    cdf = np.cumsum(P[int(condition)])
    return int(np.searchsorted(cdf, u, side="right").clip(0, N_STATES - 1))


def solo_benefit(world: World, models: SimModels) -> dict:
    """Solo accessibility loss per asset (condition-independent, so cache it once)."""
    return {a.asset_id: models.acc.loss(failed_nodes=[a.node]) for a in world.assets.values()}


def _simulate_one(policy, world0: World, scen: ScenarioSet, models: SimModels, s: int,
                  benefit: dict | None = None):
    world = world0.clone()
    asset_ids = scen.asset_ids
    idx = {a: i for i, a in enumerate(asset_ids)}
    person_days = 0.0
    planned = 0.0
    emergency = 0.0
    n_failures = 0

    if benefit is None:
        benefit = solo_benefit(world, models)

    for y in range(scen.years):
        # 1. interventions
        ctx = _context_for(world, models, benefit)
        chosen = policy.propose(list(world.assets.values()), ctx)
        for asset_id, opt in chosen.items():
            a = world.assets[asset_id]
            planned += models.sor.cost(a.structure_type, opt)
            a.condition = apply_condition(a.condition, opt)  # improves before deterioration

        # 2. deteriorate
        det = scen.det_u[s][y]
        for a in world.assets.values():
            a.condition = _sample_next_state(a.condition, models.transition, det[idx[a.asset_id]])
            a.age += 1

        # 3+4. draw failures with CRN
        rain = scen.rain[s][y]
        fail_u = scen.fail_u[s][y]
        failed_assets = []
        for a in world.assets.values():
            p = failure_probability(a.condition, float(rain[idx[a.asset_id]]), models.fragility)
            if fail_u[idx[a.asset_id]] < p:
                failed_assets.append(a)

        # 5. consequence
        if failed_assets:
            nodes = [a.node for a in failed_assets]
            loss = models.acc.loss(failed_nodes=nodes)
            mean_outage = float(np.mean([models.outage(a) for a in failed_assets]))
            person_days += mean_outage * loss
            n_failures += len(failed_assets)
            for a in failed_assets:  # emergency restoration
                emergency += models.sor.emergency_cost(a.structure_type, Intervention.MAJOR,
                                                       models.premium)
                a.condition = 0  # restored
        world.year += 1
    return person_days, planned, emergency, n_failures, world


def _context_for(world: World, models: SimModels, benefit: dict):
    from rra.simulator.policies import PolicyContext

    return PolicyContext(
        sor=models.sor,
        budget_crore=world.budget_crore,
        crew_days=world.crew_days,
        benefit=benefit,
        criticality={a.asset_id: 1.0 + a.condition for a in world.assets.values()},
        rng=np.random.default_rng(0),
    )


def run(policy, world0: World, scen: ScenarioSet, models: SimModels) -> PolicyOutcome:
    """Run one policy over all scenarios; paired with other policies on the same set."""
    benefit = solo_benefit(world0, models)
    pd = np.zeros(scen.n)
    pl = np.zeros(scen.n)
    em = np.zeros(scen.n)
    for s in range(scen.n):
        p, planned, emergency, _, _ = _simulate_one(policy, world0, scen, models, s, benefit)
        pd[s] = p
        pl[s] = planned
        em[s] = emergency
    return PolicyOutcome(
        name=getattr(policy, "name", "policy"), person_days=pd, planned=pl, emergency=em
    )


def run_all(policies, world0: World, scen: ScenarioSet, models: SimModels) -> dict:
    return {getattr(p, "name", f"policy{i}"): run(p, world0, scen, models)
            for i, p in enumerate(policies)}
