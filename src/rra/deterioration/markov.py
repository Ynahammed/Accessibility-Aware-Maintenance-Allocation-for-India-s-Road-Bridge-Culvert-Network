"""M0 — age-class Markov chain, the agency-style baseline (plan section 5.4).

Four ordered condition states: Good, Fair, Poor, Severe. Transitions are estimated from
inspection histories, with Laplace smoothing and Dirichlet bootstrap for uncertainty on
each transition row. This is deliberately the *honest* baseline the ML models (M1, M2)
must beat — never a strawman.

Validation is slipped by inspection year in the experiment harness (WP9), not here; this
module only fits and forecasts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

STATES: tuple[str, ...] = ("Good", "Fair", "Poor", "Severe")
N_STATES = len(STATES)
POOR_OR_WORSE = (2, 3)


def state_index(name: str) -> int:
    return STATES.index(name)


def transition_counts(histories) -> np.ndarray:
    """Count state->state transitions across a list of state sequences.

    ``histories`` is an iterable of sequences of state indices, ordered by year.
    """
    counts = np.zeros((N_STATES, N_STATES), dtype=float)
    for seq in histories:
        for a, b in zip(seq, seq[1:]):
            counts[int(a), int(b)] += 1.0
    return counts


def transition_counts_by_age(histories, n_classes: int, class_width: int) -> np.ndarray:
    """Transitions bucketed by asset age at the start of the transition.

    ``histories`` is an iterable of ``(ages, states)`` aligned lists. Returns an array of
    shape ``(n_classes, N_STATES, N_STATES)``; the last class absorbs all older ages.
    """
    counts = np.zeros((n_classes, N_STATES, N_STATES), dtype=float)
    for ages, states in histories:
        for i in range(len(states) - 1):
            bucket = min(int(ages[i]) // class_width, n_classes - 1)
            counts[bucket, int(states[i]), int(states[i + 1])] += 1.0
    return counts


def fit_transition_matrix(counts: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    """Laplace-smoothed row-stochastic transition matrix."""
    counts = np.asarray(counts, dtype=float)
    if counts.shape != (N_STATES, N_STATES):
        raise ValueError(f"counts must be {(N_STATES, N_STATES)}, got {counts.shape}")
    if alpha <= 0:
        raise ValueError("alpha must be positive")
    P = counts + alpha
    return P / P.sum(axis=1, keepdims=True)


def bootstrap_transition_matrices(
    counts: np.ndarray, n: int, rng: np.random.Generator | int, alpha: float = 0.5
) -> list[np.ndarray]:
    """Draw ``n`` matrices from the Dirichlet posterior of each smoothed row."""
    if isinstance(rng, (int, np.integer)):
        rng = np.random.default_rng(int(rng))
    counts = np.asarray(counts, dtype=float)
    draws: list[np.ndarray] = []
    for _ in range(n):
        P = np.vstack([rng.dirichlet(counts[i] + alpha) for i in range(N_STATES)])
        draws.append(P)
    return draws


def forecast_distribution(p0, P: np.ndarray, steps: int) -> np.ndarray:
    """Distribution over states after 0..``steps`` years; shape ``(steps+1, N_STATES)``."""
    p0 = np.asarray(p0, dtype=float)
    if p0.shape != (N_STATES,):
        raise ValueError(f"p0 must have {N_STATES} entries")
    out = np.zeros((steps + 1, N_STATES))
    out[0] = p0
    p = p0.copy()
    for t in range(1, steps + 1):
        p = p @ P
        out[t] = p
    return out


def first_passage_distribution(
    P: np.ndarray, p0, targets=POOR_OR_WORSE, max_steps: int = 50
) -> np.ndarray:
    """Distribution of the first year the chain enters ``targets``.

    Returns an array of length ``max_steps + 1``; index 0 is the mass already in
    ``targets`` at the start (a structure already Poor has passage time 0), index ``t``
    is P(first hit at year t), and the entries sum to ``1 - P(never hit by max_steps)``.

    ``q`` is the *sub-probability* of staying outside the target set. It is never
    renormalised: the mass that hits is removed, so ``sum(q)`` decays as the chain hits.
    """
    p0 = np.asarray(p0, dtype=float)
    target_mask = np.zeros(N_STATES, dtype=bool)
    target_mask[list(targets)] = True
    out = np.zeros(max_steps + 1)
    out[0] = p0[target_mask].sum()
    q = p0.copy()
    q[target_mask] = 0.0
    for t in range(1, max_steps + 1):
        q = q @ P
        hit = q[target_mask].sum()
        out[t] = hit
        q[target_mask] = 0.0
    return out


def expected_time_to(P: np.ndarray, p0, targets=POOR_OR_WORSE, max_steps: int = 50) -> float:
    """Expected first-passage year into ``targets`` (censored at ``max_steps``)."""
    dist = first_passage_distribution(P, p0, targets, max_steps)
    years = np.arange(len(dist))
    return float((dist * years).sum())


@dataclass
class AgeClassMarkov:
    """M0 with age-dependent transition matrices."""

    matrices: np.ndarray  # (n_classes, N_STATES, N_STATES)
    class_width: int

    def matrix_for_age(self, age: int) -> np.ndarray:
        bucket = min(int(age) // self.class_width, self.matrices.shape[0] - 1)
        return self.matrices[bucket]

    def forecast(self, state: int, age: int, steps: int) -> np.ndarray:
        """Forecast one structure, advancing age each year (age-dependent matrices)."""
        out = np.zeros((steps + 1, N_STATES))
        p = np.zeros(N_STATES)
        p[int(state)] = 1.0
        out[0] = p
        a = int(age)
        for t in range(1, steps + 1):
            p = p @ self.matrix_for_age(a)
            out[t] = p
            a += 1
        return out
