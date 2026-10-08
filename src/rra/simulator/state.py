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
