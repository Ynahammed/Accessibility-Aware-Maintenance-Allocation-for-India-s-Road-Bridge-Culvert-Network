"""Accessibility-aware maintenance allocation for India's road-bridge-culvert network.

Package root. See BUILD_PLAN.md for the work-package order.

Every number produced anywhere in this package must be tagged as one of:
    "real"    - read from a source dataset (PMGSY, OSM, IMD, NBI, PWD SoR ...)
    "fitted"  - estimated from data with a stated model
    "assumed" - a policy/parametric choice recorded in the assumptions register
"""

__version__ = "0.0.1"
