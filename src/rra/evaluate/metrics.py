"""Metrics (plan sections 5.4 and 6).

Forecast metrics for deterioration (log-loss, ranked probability score, concordance for
time-to-Poor) and the policy metric (person-days of access lost per ₹ crore spent).
"""

from __future__ import annotations

import numpy as np

from rra.deterioration.markov import N_STATES


def log_loss(y_true, proba, eps: float = 1e-12) -> float:
    """Mean negative log-likelihood of the realised state."""
    y = np.asarray(y_true, dtype=int)
    p = np.clip(np.asarray(proba, dtype=float), eps, 1.0)
    return float(-np.mean(np.log(p[np.arange(y.size), y])))


def ranked_probability_score(y_true, proba) -> float:
    """RPS for an ordered categorical forecast (lower is better)."""
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(proba, dtype=float)
    n = y.size
    obs = np.zeros((n, N_STATES))
    obs[np.arange(n), y] = 1.0
    cum_p = np.cumsum(p, axis=1)
    cum_o = np.cumsum(obs, axis=1)
    return float(np.mean(np.sum((cum_p - cum_o) ** 2, axis=1)))


def concordance_index(times, scores, events) -> float:
    """Harrell's C for time-to-event: higher score should mean earlier event."""
    times = np.asarray(times, dtype=float)
    scores = np.asarray(scores, dtype=float)
    events = np.asarray(events, dtype=int)
    concordant = discordant = 0.0
    n = times.size
    for i in range(n):
        if not events[i]:
            continue
        for j in range(n):
            if i == j:
                continue
            if times[j] > times[i]:  # i had the event first
                if scores[i] > scores[j]:
                    concordant += 1
                elif scores[i] < scores[j]:
                    discordant += 1
                # ties in score count as 0.5
                else:
                    concordant += 0.5
                    discordant += 0.5
    denom = concordant + discordant
    return float(concordant / denom) if denom else 0.5


def access_lost_per_crore(person_days_lost, spend_crore) -> float:
    """The plan's primary metric: person-days of access lost per ₹ crore spent."""
    spend = float(spend_crore)
    if spend <= 0:
        return float("inf")
    return float(person_days_lost) / spend
