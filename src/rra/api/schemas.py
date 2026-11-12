"""Request/response schemas for the HTTP API.

Field bounds mirror the service-layer clamps so that obviously bad input is rejected
with a 422 before it reaches the simulator; the services still clamp defensively.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    preset: Literal["generic", "redundant"] = "generic"
    budget_crore: float = Field(0.6, ge=0.0, le=5.0, description="Annual budget, ₹ crore")
    stress: float = Field(0.0, ge=-1.0, le=2.0, description="Mean log rainfall ratio")
    seed: int = Field(0, ge=0, le=999)
    scenarios: int = Field(8, ge=1, le=32)
    years: int = Field(3, ge=1, le=5)
    redundancy: int = Field(2, ge=1, le=4, description="Parallel routes per corridor")


class LossRequest(BaseModel):
    redundancy: int = Field(2, ge=1, le=4)
    seed: int = Field(0, ge=0, le=999)
    failed: list[str] = Field(default_factory=list, max_length=12)


class PlanRequest(BaseModel):
    budget_crore: float | None = Field(None, ge=0.0, le=5.0)
    crew_days: float | None = Field(None, ge=0.0, le=5000.0)
    seed: int = Field(0, ge=0, le=999)
    scenarios: int = Field(8, ge=2, le=32)
    years: int = Field(1, ge=1, le=5)


class ConsequenceRequest(BaseModel):
    failed: list[str] = Field(default_factory=list, max_length=64)
    seed: int = Field(0, ge=0, le=999)


class SimulateRequest(BaseModel):
    budget_crore: float | None = Field(None, ge=0.0, le=5.0)
    stress: float = Field(0.0, ge=-1.0, le=2.0)
    seed: int = Field(0, ge=0, le=999)
    scenarios: int = Field(8, ge=1, le=32)
    years: int = Field(3, ge=1, le=5)
