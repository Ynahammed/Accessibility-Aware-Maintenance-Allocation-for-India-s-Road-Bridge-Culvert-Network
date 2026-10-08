"""Rainfall scenarios (plan section 5.2).

Two families of scenario:

* **(a) resample historical monsoon years as spatial fields** — keeps the real
  cross-cell correlation, because an entire year's field is drawn together;
* **(b) stress events** — scale a field to a chosen return level.

Both produce arrays of shape ``(n_scenarios, n_cells)`` suitable for the simulator.
"""

from __future__ import annotations

import numpy as np


def resample_year_fields(annual_fields, n: int, rng: np.random.Generator | int) -> np.ndarray:
    """Draw ``n`` scenario fields by resampling whole historical years with replacement.

    Parameters
    ----------
    annual_fields: shape ``(n_years, n_cells)`` — one observed monsoon field per year.
    n:             number of scenarios to draw.
    rng:           seed or Generator.

    Resampling whole *rows* (years) is what preserves spatial correlation: cells rise and
    fall together exactly as they did in the observed years.
    """
    if isinstance(rng, (int, np.integer)):
        rng = np.random.default_rng(int(rng))
    fields = np.asarray(annual_fields, dtype=float)
    if fields.ndim != 2:
        raise ValueError("annual_fields must be 2-D (n_years, n_cells)")
    if fields.shape[0] == 0:
        raise ValueError("no historical years to resample")
    idx = rng.integers(0, fields.shape[0], size=n)
    return fields[idx, :]


def stress_scaled(field, factor: float) -> np.ndarray:
    """Scale a rainfall field by a constant factor (stress-event construction)."""
    if factor <= 0:
        raise ValueError(f"factor must be positive, got {factor}")
    return np.asarray(field, dtype=float) * factor


def stress_to_return_level(
    base_field, target_level: float, base_level: float
) -> np.ndarray:
    """Scale a base field so its mean cell reaches ``target_level``.

    ``base_level`` is the field's current reference mean (e.g. its 2-year return level
    mean); the ratio is applied uniformly, preserving spatial pattern.
    """
    if base_level <= 0:
        raise ValueError("base_level must be positive")
    return stress_scaled(base_field, target_level / base_level)
