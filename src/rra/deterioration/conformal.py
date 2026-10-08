"""Split-conformal uncertainty (plan section 5.4).

Given a point predictor (e.g. ``median_time`` from M2) and a calibration set never used
for fitting, split conformal gives finite-sample coverage guarantees under exchangeability:

    interval(x) = [ f(x) - q , f(x) + q ],   q = the ceil((n+1)(1-alpha))-th
                                             smallest absolute residual.

Class-conditional intervals use residuals from the same structure type, which is what
the plan asks for ("class-conditional by structure type"). E2 checks realised coverage
against the target, before and after recalibration.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SplitConformal:
    residuals: np.ndarray  # absolute calibration residuals |y - f(x)|

    def quantile(self, alpha: float) -> float:
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        res = np.sort(np.asarray(self.residuals, dtype=float))
        n = res.size
        if n == 0:
            raise ValueError("no calibration residuals")
        k = int(np.ceil((n + 1) * (1.0 - alpha)))
        return float(res[min(k, n) - 1])

    def interval(self, point, alpha: float = 0.1):
        q = self.quantile(alpha)
        point = np.asarray(point, dtype=float)
        return point - q, point + q

    @staticmethod
    def coverage(y_true, lo, hi) -> float:
        y = np.asarray(y_true, dtype=float)
        return float(np.mean((y >= np.asarray(lo)) & (y <= np.asarray(hi))))


class ClassConditionalConformal:
    """One :class:`SplitConformal` per group (e.g. structure type)."""

    def __init__(self):
        self.by_group: dict = {}

    def fit(self, residuals, groups) -> "ClassConditionalConformal":
        res = np.asarray(residuals, dtype=float)
        for g in np.unique(np.asarray(groups)):
            self.by_group[g] = SplitConformal(res[np.asarray(groups) == g])
        return self

    def interval(self, point, group, alpha: float = 0.1):
        if group in self.by_group:
            return self.by_group[group].interval(point, alpha)
        # fall back to the pooled residuals if a group is unseen
        pooled = np.concatenate([c.residuals for c in self.by_group.values()])
        return SplitConformal(pooled).interval(point, alpha)
