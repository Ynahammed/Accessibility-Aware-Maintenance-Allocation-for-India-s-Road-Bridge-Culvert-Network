"""World state for the simulator."""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class Asset:
    asset_id: str
    structure_type: str
    node: str  # graph node representing the structure
    age: int = 0
    condition: int = 0  # 0 Good .. 3 Severe
    # Fragility multiplier bought by *this year's* planned intervention (plan 5.5:
    # an intervention resets condition and also cuts failure risk directly). It is
    # reset to 1.0 at the start of every simulated year, so the effect lasts for the
    # monsoon window it was paid for — the same one-year semantics the optimizer uses.
    fragility_mult: float = 1.0


@dataclass
class World:
    assets: dict[str, Asset]
    budget_crore: float
    crew_days: float
    year: int = 0

    def clone(self) -> "World":
        return World(
            assets={k: replace(v) for k, v in self.assets.items()},
            budget_crore=self.budget_crore,
            crew_days=self.crew_days,
            year=self.year,
        )
