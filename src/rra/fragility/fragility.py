"""Fragility model (plan section 5.5).

    Pr(fail | c, R) = sigmoid( beta0 + beta1 * g(c) + beta2 * log(R / R_ref) )

``g(c)`` maps the condition state to a numeric score (Good=0 ... Severe=3), ``R`` the
local rainfall level and ``R_ref`` the reference scale. Parameters are assumptions with
literature-informed ranges, varied in E8 rather than claimed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def condition_score(state: int) -> float:
    """Map a condition state index to its numeric score."""
    return float(int(state))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass(frozen=True)
class FragilityParams:
    beta0: float
    beta1: float
    beta2: float
    rain_ref_level: float = 1.0

    @classmethod
    def from_register(cls, register) -> "FragilityParams":
        return cls(
            beta0=register["fragility_beta0"].default,
            beta1=register["fragility_beta1"].default,
            beta2=register["fragility_beta2"].default,
            rain_ref_level=1.0,  # R is already expressed as a ratio to the local level
        )


def failure_probability(condition: int, rain_ratio: float, params: FragilityParams) -> float:
    """Probability that an asset fails, given condition and rainfall ratio (R/R_ref)."""
    if rain_ratio <= 0:
        raise ValueError(f"rain_ratio must be positive, got {rain_ratio}")
    logit = params.beta0 + params.beta1 * condition_score(condition) + params.beta2 * math.log(
        rain_ratio / params.rain_ref_level
    )
    return _sigmoid(logit)


def failure_probabilities(conditions, rain_ratios, params: FragilityParams):
    """Vectorised convenience wrapper."""
    return [failure_probability(c, r, params) for c, r in zip(conditions, rain_ratios)]
