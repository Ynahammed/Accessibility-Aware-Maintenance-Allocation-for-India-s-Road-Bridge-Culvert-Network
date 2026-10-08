"""The living assumptions register.

The plan treats unobservable quantities (no Indian failure labels, no repair-time
records) as *stated assumptions that get varied*, never as claims. This module is the
single source of truth for those quantities. Every downstream sweep, sensitivity axis
and regret analysis pulls its ranges from here, so the register is a real dependency
rather than documentation that rots.

Design notes
------------
* A ``Parameter`` carries ``low``/``high`` (the sweep range), a ``default`` (the
  pre-registered point value) and a ``source`` tag (``real`` | ``fitted`` | ``assumed``).
* ``AssumptionRegister.sample`` draws one parameter set with a seed. Draws are uniform
  in the range by default so the sweep is honest and easy to explain; per-parameter
  distributions can be added without changing the caller.
* ``to_markdown`` renders the register for ``docs/assumptions.md`` so the document and
  the code can never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, replace
from typing import Literal

import numpy as np

SourceTag = Literal["real", "fitted", "assumed"]


@dataclass(frozen=True)
class Parameter:
    """One swept quantity.

    Attributes
    ----------
    name:   stable key used in code and configs.
    unit:   human-readable unit, for the rendered register.
    low/high: inclusive sweep range.
    default: pre-registered point value (must lie in [low, high]).
    source:  provenance tag.
    why:    one line on why the quantity is needed (mirrors the plan's register).
    how:    one line on how it is varied.
    """

    name: str
    unit: str
    low: float
    high: float
    default: float
    source: SourceTag
    why: str
    how: str

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"{self.name}: low {self.low} > high {self.high}")
        if not (self.low <= self.default <= self.high):
            raise ValueError(
                f"{self.name}: default {self.default} outside [{self.low}, {self.high}]"
            )

    def sample(self, rng: np.random.Generator) -> float:
        """Draw one value uniformly from the sweep range."""
        if self.low == self.high:
            return float(self.low)
        return float(rng.uniform(self.low, self.high))


# --- Default register -------------------------------------------------------------
# Ranges are literature-informed starting points, NOT measurements. They are the
# explicit subject of the sensitivity analysis (E8): the headline claim must be a
# policy that is near-best *across* these ranges.

DEFAULT_PARAMETERS: tuple[Parameter, ...] = (
    # --- fragility: Pr(fail | condition c, rainfall ratio R) = sigmoid(b0 + b1 g(c) + b2 log(R/Rref))
    Parameter(
        "fragility_beta0", "logit", -6.0, -1.0, -3.0, "assumed",
        "Baseline failure log-odds; no Indian failure labels exist.",
        "Swept across the range; reported as a sensitivity axis.",
    ),
    Parameter(
        "fragility_beta1", "logit per condition step", 0.3, 3.0, 1.2, "assumed",
        "Condition drives failure probability.",
        "Swept slope; threshold behaviour tested.",
    ),
    Parameter(
        "fragility_beta2", "logit per log rain ratio", 0.5, 4.0, 2.0, "assumed",
        "Rainfall loading above the local reference level.",
        "Swept slope.",
    ),
    Parameter(
        "fragility_rain_ref_level", "return period (years)", 2.0, 10.0, 5.0, "assumed",
        "Reference rainfall event defining R=1.",
        "Swept; stress scenarios use fixed return levels.",
    ),
    # --- deterioration transfer
    Parameter(
        "deterioration_acceleration", "multiplier", 1.0, 3.0, 1.5, "assumed",
        "Indian climate/load/maintenance differ from NBI conditions.",
        "Multiplier on hazard rates; reported as a sensitivity axis.",
    ),
    # --- repair effectiveness
    Parameter(
        "repair_effect_minor", "condition-step reset", 0.0, 1.0, 0.5, "assumed",
        "Minor repair effect on condition.",
        "Range per intervention type; regret reported.",
    ),
    Parameter(
        "repair_effect_major", "condition-step reset", 1.0, 3.0, 2.0, "assumed",
        "Major repair effect on condition.",
        "Range per intervention type; regret reported.",
    ),
    Parameter(
        "repair_effect_replace", "condition-step reset", 3.0, 4.0, 4.0, "assumed",
        "Replacement resets to Good.",
        "Effectively full reset.",
    ),
    # --- outage
    Parameter(
        "outage_mean_days_culvert", "days", 3.0, 30.0, 10.0, "assumed",
        "Outage duration after failure (no repair-time records).",
        "Swept mean by structure type.",
    ),
    Parameter(
        "outage_mean_days_minor_bridge", "days", 7.0, 90.0, 30.0, "assumed",
        "Outage duration after failure.",
        "Swept mean by structure type.",
    ),
    Parameter(
        "outage_mean_days_major_bridge", "days", 30.0, 365.0, 120.0, "assumed",
        "Outage duration after failure.",
        "Swept mean by structure type.",
    ),
    # --- cost
    Parameter(
        "emergency_premium", "multiplier", 1.0, 3.0, 1.8, "assumed",
        "Restoring a failed asset costs more than a planned repair.",
        "Swept multiplier.",
    ),
    # --- consequence policy knobs
    Parameter(
        "facility_weight_health", "weight", 0.5, 3.0, 1.0, "assumed",
        "Relative importance of access to health services.",
        "Grid over weights; rank-stability tests.",
    ),
    Parameter(
        "facility_weight_school", "weight", 0.5, 3.0, 1.0, "assumed",
        "Relative importance of access to schools.",
        "Grid over weights; rank-stability tests.",
    ),
    Parameter(
        "travel_time_cap_health", "minutes", 30.0, 120.0, 60.0, "assumed",
        "Acceptable travel time to a health facility.",
        "Grid over caps; rank-stability tests.",
    ),
    Parameter(
        "travel_time_cap_school", "minutes", 20.0, 90.0, 45.0, "assumed",
        "Acceptable travel time to a school.",
        "Grid over caps; rank-stability tests.",
    ),
    # --- network
    Parameter(
        "snap_tolerance_m", "metres", 10.0, 50.0, 25.0, "assumed",
        "Distance within which an asset attaches to the nearest network node.",
        "Fixed near 25 m; logged overshoots.",
    ),
    Parameter(
        "speed_rural_kph", "km/h", 20.0, 40.0, 30.0, "assumed",
        "Free-flow speed on rural (PMGSY) roads.",
        "Fixed; sensitivity checked.",
    ),
    Parameter(
        "speed_state_kph", "km/h", 40.0, 60.0, 50.0, "assumed",
        "Free-flow speed on state highways.",
        "Fixed; sensitivity checked.",
    ),
    Parameter(
        "speed_national_kph", "km/h", 60.0, 90.0, 70.0, "assumed",
        "Free-flow speed on national highways.",
        "Fixed; sensitivity checked.",
    ),
    Parameter(
        "speed_connector_kph", "km/h", 3.0, 15.0, 5.0, "assumed",
        "Last-mile (walking) speed on the connector from an asset to the road node.",
        "Fixed; sensitivity checked.",
    ),
)


@dataclass
class AssumptionRegister:
    """A collection of parameters that can be sampled, rendered and diffed."""

    parameters: dict[str, Parameter] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "AssumptionRegister":
        return cls({p.name: p for p in DEFAULT_PARAMETERS})

    # -- lookups -------------------------------------------------------------------
    def __getitem__(self, name: str) -> Parameter:
        return self.parameters[name]

    def names(self) -> list[str]:
        return list(self.parameters)

    def point_values(self) -> dict[str, float]:
        """The pre-registered default set (used before a sweep is run)."""
        return {name: p.default for name, p in self.parameters.items()}

    def with_values(self, values: dict) -> "AssumptionRegister":
        """A new register whose defaults are overridden by ``values`` (a sampled draw)."""
        out = {}
        for name, p in self.parameters.items():
            out[name] = replace(p, default=float(values[name])) if name in values else p
        return AssumptionRegister(out)

    def sample(self, rng: np.random.Generator | int, n: int = 1) -> list[dict[str, float]]:
        """Draw ``n`` parameter sets. Reproducible for a given integer seed."""
        if isinstance(rng, (int, np.integer)):
            rng = np.random.default_rng(int(rng))
        draws: list[dict[str, float]] = []
        for _ in range(n):
            draws.append({name: p.sample(rng) for name, p in self.parameters.items()})
        return draws

    def to_markdown(self) -> str:
        lines = [
            "# Assumptions register",
            "",
            "Auto-generated from `src/rra/assumptions.py` — do not edit by hand.",
            "Every entry is an **assumed** or **fitted** quantity that is *varied*, not claimed.",
            "",
            "| Parameter | Unit | Range | Default | Source | Why needed | How varied |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in self.parameters.values():
            rng = f"{p.low:g}–{p.high:g}"
            lines.append(
                f"| `{p.name}` | {p.unit} | {rng} | {p.default:g} | {p.source} | "
                f"{p.why} | {p.how} |"
            )
        lines.append("")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, dict]:
        return {name: asdict(p) for name, p in self.parameters.items()}
