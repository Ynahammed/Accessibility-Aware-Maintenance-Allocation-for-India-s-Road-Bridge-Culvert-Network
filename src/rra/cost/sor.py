"""Schedule of Rates (plan section 5.5).

Cost per intervention comes from the state PWD Schedule of Rates where obtainable. **All
monetary values here are in ₹ crore**, which is the unit the budget constraint and the
primary metric (person-days per crore) use — keeping one unit everywhere avoids the classic
lakh/crore mix-up. The defaults are placeholders tagged **assumed** until real SoR tables
are entered.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .interventions import COST_MULTIPLIER, LABOUR_MULTIPLIER, Intervention

# placeholder base *minor* repair cost in ₹ crore per structure type — ASSUMED
DEFAULT_BASE_COST_CRORE: dict[str, float] = {
    "culvert": 0.02,
    "minor_bridge": 0.08,
    "major_bridge": 0.25,
    "road_segment": 0.03,
}
# crew-days for a day's work
DEFAULT_LABOUR_DAYS: dict[str, float] = {
    "culvert": 5.0,
    "minor_bridge": 20.0,
    "major_bridge": 60.0,
    "road_segment": 8.0,
}


@dataclass
class ScheduleOfRates:
    base_cost_crore: dict = field(default_factory=lambda: dict(DEFAULT_BASE_COST_CRORE))
    labour_days: dict = field(default_factory=lambda: dict(DEFAULT_LABOUR_DAYS))
    source: str = "assumed (placeholder until PWD SoR entered)"

    def cost(self, structure_type: str, intervention: Intervention) -> float:
        """Planned cost in ₹ crore."""
        if structure_type not in self.base_cost_crore:
            raise KeyError(f"unknown structure_type {structure_type!r}")
        return self.base_cost_crore[structure_type] * COST_MULTIPLIER[intervention.value]

    def labour(self, structure_type: str, intervention: Intervention) -> float:
        """Crew-days required."""
        return self.labour_days[structure_type] * LABOUR_MULTIPLIER[intervention.value]

    def emergency_cost(
        self, structure_type: str, intervention: Intervention, premium: float
    ) -> float:
        """Cost of restoring a *failed* asset (planned cost times premium), in ₹ crore."""
        return self.cost(structure_type, intervention) * float(premium)
