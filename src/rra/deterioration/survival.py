"""M2 — discrete-time survival for time to Poor (plan section 5.4).

Pooled logistic hazard over discrete years. Each observation ``(x, duration, event)`` is
expanded into one row per year survived, with the year index as an extra feature; the
hazard ``h(t|x)`` is a logistic in ``(x, t)``. Survival is ``S(t) = prod_{s<=t}(1-h(s))``
and the time-to-event distribution is ``S(t-1) h(t)``.

A self-contained implementation keeps lifelines optional while preserving the same
declared interface, so E1 can still compare M0/M1/M2 honestly.
"""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression


class DiscreteTimeSurvival:
    def __init__(self, max_time: int = 20, random_state: int = 0):
        self.max_time = int(max_time)
        self.model: LogisticRegression | None = None

    def _expand(self, X, durations, events):
        X = np.asarray(X, dtype=float)
        rows, labels = [], []
        for xi, d, e in zip(X, durations, events):
            d = int(min(max(int(d), 1), self.max_time))
            for t in range(1, d + 1):
                rows.append(np.concatenate([xi, [float(t)]]))
                labels.append(1 if (t == d and int(e) == 1) else 0)
        return np.asarray(rows), np.asarray(labels, dtype=int)

    def fit(self, X, durations, events) -> "DiscreteTimeSurvival":
        rows, labels = self._expand(X, durations, events)
        # guard against a single-class label set (degenerate toy data)
        if len(np.unique(labels)) < 2:
            self.model = None
            return self
        self.model = LogisticRegression(max_iter=1000)
        self.model.fit(rows, labels)
        return self

    def predict_hazard(self, X) -> np.ndarray:
        """hazard[h, t] for t = 1..max_time."""
        X = np.asarray(X, dtype=float)
        n = X.shape[0]
        hz = np.zeros((n, self.max_time))
        if self.model is None:
            return hz
        for t in range(1, self.max_time + 1):
            rows = np.hstack([X, np.full((n, 1), float(t))])
            hz[:, t - 1] = self.model.predict_proba(rows)[:, 1]
        return hz

    def predict_survival(self, X) -> np.ndarray:
        """S[:, t] for t = 0..max_time, with S[:, 0] = 1."""
        hz = self.predict_hazard(X)
        S = np.ones((hz.shape[0], self.max_time + 1))
        S[:, 1:] = np.cumprod(1.0 - hz, axis=1)
        return S

    def time_distribution(self, X) -> np.ndarray:
        """P(T = t) for t = 1..max_time plus a final 'beyond max_time' bucket."""
        n = np.asarray(X, dtype=float).shape[0]
        S = self.predict_survival(X)
        hz = self.predict_hazard(X)
        pmf = np.zeros((n, self.max_time + 1))
        pmf[:, 0] = 0.0
        for t in range(1, self.max_time + 1):
            pmf[:, t] = S[:, t - 1] * hz[:, t - 1]
        pmf[:, self.max_time] += S[:, self.max_time]  # right-censored mass
        return pmf

    def median_time(self, X) -> np.ndarray:
        S = self.predict_survival(X)
        below = S < 0.5
        idx = np.where(below.any(axis=1), below.argmax(axis=1), self.max_time)
        return idx.astype(float)
