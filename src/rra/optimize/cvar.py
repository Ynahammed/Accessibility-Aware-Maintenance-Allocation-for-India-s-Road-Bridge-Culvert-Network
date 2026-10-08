"""Conditional value at risk (plan sections 5.6/5.7).

CVaR at level ``alpha`` is the mean of the worst ``alpha`` fraction of outcomes. It is
the tail metric the plan asks for alongside the mean, and it enters the optimizer through
the ``eta + 1/((1-alpha)|Omega|) sum z`` term.
"""

from __future__ import annotations

import numpy as np


def cvar(losses, alpha: float = 0.05) -> float:
    """Mean of the worst ``alpha`` fraction of ``losses`` (larger = worse)."""
    if not 0.0 < alpha <= 1.0:
        raise ValueError(f"alpha must be in (0, 1], got {alpha}")
    x = np.sort(np.asarray(losses, dtype=float))[::-1]
    k = max(1, int(np.ceil(alpha * x.size)))
    return float(x[:k].mean())


def value_at_risk(losses, alpha: float = 0.05) -> float:
    """The ``1 - alpha`` quantile (threshold of the worst tail)."""
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    return float(np.quantile(np.asarray(losses, dtype=float), 1.0 - alpha))
