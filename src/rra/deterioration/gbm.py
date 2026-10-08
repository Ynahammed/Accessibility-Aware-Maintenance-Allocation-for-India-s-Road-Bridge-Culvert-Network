"""M1 — gradient boosting for next-year condition state (plan section 5.4).

A pure ``sklearn`` wrapper so the interface matches M0/M2. Swapping in LightGBM later is
a one-line change behind ``predict_proba``. ``predict_proba`` always returns an
``(n, 4)`` array in the canonical state order even if a class is absent from training.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier

from .markov import N_STATES


class GradientBoostingDeterioration:
    def __init__(self, n_estimators: int = 100, max_depth: int = 3, random_state: int = 0):
        self.model = GradientBoostingClassifier(
            n_estimators=n_estimators, max_depth=max_depth, random_state=random_state
        )
        self.classes_: np.ndarray | None = None

    def fit(self, X, y) -> "GradientBoostingDeterioration":
        self.model.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=int))
        self.classes_ = self.model.classes_
        return self

    def predict_proba(self, X) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        raw = self.model.predict_proba(X)
        out = np.zeros((X.shape[0], N_STATES))
        for j, c in enumerate(self.classes_):
            out[:, int(c)] = raw[:, j]
        return out

    def predict(self, X) -> np.ndarray:
        return self.predict_proba(X).argmax(axis=1)
