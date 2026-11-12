"""Application services: the product layer over the research modules.

The FastAPI app (``rra.api``) and the local stdlib server (``rra.serve``) are thin
transports over these services, so every number shown in the UI comes from the same
code path the experiment scripts use.

Modules
-------
``districts``  study-district registry and builders
``lab``        paired policy experiments and set-based consequence queries
``planning``   the recommended year-1 maintenance plan for a district and budget
``evidence``   frozen experiment results, data availability and the assumptions register
``register``   the live register: defaults plus validated PWD/RTI overrides and prices
"""

from __future__ import annotations

from .districts import (
    DISTRICTS,
    build_district,
    build_world_models,
    get_spec,
    list_districts,
    network_view,
)
from .evidence import get_evidence, load_evidence
from .lab import POLICY_ORDER, consequence, normalize_params, run_experiment, run_loss
from .planning import build_plan
from .register import live_register

__all__ = [
    "DISTRICTS",
    "POLICY_ORDER",
    "build_district",
    "build_plan",
    "build_world_models",
    "consequence",
    "get_evidence",
    "get_spec",
    "list_districts",
    "live_register",
    "load_evidence",
    "network_view",
    "normalize_params",
    "run_experiment",
    "run_loss",
]
