"""Interventions (plan section 5.5).

Four options per asset: none, minor repair, major repair, replacement. Each has a cost
(from the state Schedule of Rates), a labour requirement, and an effect on condition and
on fragility. A failed asset restored in an emergency pays an extra premium over the
planned-repair cost — a swept parameter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from rra.deterioration.markov import N_STATES

# roughness multiplier on cost for major vs minor work
COST_MULTIPLIER: dict[str, float] = {
    "none": 0.0,
    "minor": 1.0,
    "major": 4.0,
    "replace": 12.0,
}
LABOUR_MULTIPLIER: dict[str, float] = {
    "none": 0.0,
    "minor": 1.0,
    "major": 2.5,
    "replace": 6.0,
}


class Intervention(str, Enum):
    NONE = "none"
    MINOR = "minor"
    MAJOR = "major"
    REPLACE = "replace"


@dataclass
class InterventionEffect:
    condition_reset: float  # how many severity steps are removed
    fragility_factor: float  # multiplier applied to failure probability afterwards


def effect_of(intervention: Intervention, register=None) -> InterventionEffect:
    """Read the effect from the register (falls back to sensible defaults)."""
    if register is not None:
        resets = {
            Intervention.NONE: 0.0,
            Intervention.MINOR: register["repair_effect_minor"].default,
            Intervention.MAJOR: register["repair_effect_major"].default,
            Intervention.REPLACE: register["repair_effect_replace"].default,
        }
    else:
        resets = {
            Intervention.NONE: 0.0,
            Intervention.MINOR: 0.5,
            Intervention.MAJOR: 2.0,
            Intervention.REPLACE: 4.0,
        }
    # a repair that resets condition by more steps also reduces fragility proportionally
    reset = resets[intervention]
    fragility_factor = math.exp(-0.35 * reset)
    return InterventionEffect(reset, fragility_factor)


def apply_condition(state: int, intervention: Intervention, register=None) -> int:
    """New condition state after an intervention (severity may decrease)."""
    reset = effect_of(intervention, register).condition_reset
    new = int(round(int(state) - reset))
    return max(0, min(N_STATES - 1, new))
