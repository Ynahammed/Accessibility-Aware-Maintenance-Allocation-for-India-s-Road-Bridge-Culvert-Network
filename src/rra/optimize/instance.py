"""Build optimization instances from the simulator's world and models (plan 5.7).

Two objectives share the same option structure:

* **additive** — ``sum_a p(fail | a, option, rain_w) * outage_a * solo_loss_a``. Linear,
  solved exactly by the MILP. ``solo_loss_a`` is the accessibility loss of failing ``a``
  *alone*, which ignores network coupling.
* **network-aware** — for each scenario and option, assets that fail form a *set* ``F_w``
  and the loss is the true set-based ``L(F_w)`` from the consequence model. Non-additive,
  optimised by local search, no optimality guarantee.

Common random numbers enter through ``crn_u`` (one uniform per asset per scenario), drawn
once so that whether an asset fails is a fixed function of the chosen option.
"""

from __future__ import annotations

import numpy as np

from rra.cost.interventions import Intervention, apply_condition, effect_of
from rra.fragility.fragility import failure_probability

OPTION_LIST: tuple[Intervention, ...] = (
    Intervention.NONE,
    Intervention.MINOR,
    Intervention.MAJOR,
    Intervention.REPLACE,
)
N_OPTIONS = len(OPTION_LIST)


def solo_losses(assets, models) -> dict:
    """Accessibility loss of each asset failing alone."""
    return {a.asset_id: models.acc.loss(failed_nodes=[a.node]) for a in assets}


def _option_arrays(assets, models, solo):
    """Return (cost, labour, condition, factor) each shaped (n_assets, N_OPTIONS)."""
    na = len(assets)
    cost = np.zeros((na, N_OPTIONS))
    labour = np.zeros((na, N_OPTIONS))
    cond = np.zeros((na, N_OPTIONS), dtype=int)
    factor = np.ones((na, N_OPTIONS))
    for i, a in enumerate(assets):
        for j, opt in enumerate(OPTION_LIST):
            cost[i, j] = models.sor.cost(a.structure_type, opt)
            labour[i, j] = models.sor.labour(a.structure_type, opt)
            cond[i, j] = apply_condition(a.condition, opt)
            factor[i, j] = effect_of(opt).fragility_factor
    return cost, labour, cond, factor


def _failure_probabilities(assets, models, rain_samples, cond, factor) -> np.ndarray:
    """p[a, j, w] probability asset a fails under option j in scenario w."""
    assets = list(assets)
    rain = np.asarray(rain_samples, dtype=float)  # (S, n_assets)
    S = rain.shape[0]
    na = len(assets)
    p = np.zeros((na, N_OPTIONS, S))
    for i, a in enumerate(assets):
        for j in range(N_OPTIONS):
            for w in range(S):
                p[i, j, w] = failure_probability(
                    int(cond[i, j]), float(max(rain[w, i], 1e-9)), models.fragility
                ) * factor[i, j]
    return p


def build_additive_instance(assets, models, rain_samples):
    """Additive instance: loss[a,j,w] = p(fail) * outage_a * solo_loss_a."""
    from .milp import AdditiveInstance

    assets = list(assets)
    na = len(assets)
    rain = np.asarray(rain_samples, dtype=float)
    S = rain.shape[0]
    solo = solo_losses(assets, models)
    cost, labour, cond, factor = _option_arrays(assets, models, solo)
    p = _failure_probabilities(assets, models, rain, cond, factor)

    loss_flat = np.zeros((na * N_OPTIONS, S))
    cost_flat = np.zeros(na * N_OPTIONS)
    labour_flat = np.zeros(na * N_OPTIONS)
    names = []
    groups = []
    for i, a in enumerate(assets):
        outage = models.outage(a)
        group = []
        for j, opt in enumerate(OPTION_LIST):
            v = i * N_OPTIONS + j
            loss_flat[v] = p[i, j, :] * outage * solo[a.asset_id]
            cost_flat[v] = cost[i, j]
            labour_flat[v] = labour[i, j]
            names.append(f"{a.asset_id}:{opt.value}")
            group.append(v)
        groups.append(group)
    return AdditiveInstance(cost_flat, labour_flat, loss_flat, groups, names)


def failure_indicators(assets, models, rain_samples, crn_u) -> np.ndarray:
    """Fixed binary failure ``f[a, j, w] = 1[crn_u < p]`` under common random numbers."""
    assets = list(assets)
    cond, factor = _option_arrays(assets, models, None)[2:]
    p = _failure_probabilities(assets, models, rain_samples, cond, factor)
    u = np.asarray(crn_u, dtype=float)  # (n_assets, S)
    return (u[:, None, :] < p).astype(bool)


def network_aware_objective(assets, models, rain_samples, crn_u, budget, crew, penalty=1e6):
    """Sample-average set-based loss with budget/crew penalties, for local search."""
    assets = list(assets)
    na = len(assets)
    rain = np.asarray(rain_samples, dtype=float)
    S = rain.shape[0]
    solo = solo_losses(assets, models)  # not used for loss, kept for parity
    cost, labour, cond, factor = _option_arrays(assets, models, solo)
    ind = failure_indicators(assets, models, rain_samples, crn_u)  # (na, N_OPTIONS, S)

    def objective(x) -> float:
        x = np.asarray(x, dtype=float)
        sel = np.zeros(na, dtype=int)
        for i in range(na):
            block = x[i * N_OPTIONS:(i + 1) * N_OPTIONS]
            sel[i] = int(np.argmax(block))
        total = 0.0
        for w in range(S):
            failed = [assets[i] for i in range(na) if ind[i, sel[i], w]]
            if failed:
                outage = float(np.mean([models.outage(a) for a in failed]))
                total += outage * models.acc.loss(failed_nodes=[a.node for a in failed])
        val = total / S
        spent = float(cost[np.arange(na), sel].sum())
        used = float(labour[np.arange(na), sel].sum())
        val += penalty * max(0.0, spent - budget)
        val += penalty * max(0.0, used - crew)
        return val

    return objective
