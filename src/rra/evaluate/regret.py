"""Robustness: win-rate and regret over the assumptions register (plan section 6).

The headline claim is a policy that is *near-best across the whole range*, not one that
wins under a single setting. For a matrix of losses indexed ``[policy, assumption_set]``:

    win_rate[p]  = fraction of sets where p is (tied-)best
    regret[p, s] = loss[p, s] - best_loss[s]

Regret is reported as a distribution (mean, max), never a single number.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Robustness:
    win_rate: np.ndarray  # (n_policies,)
    mean_regret: np.ndarray  # (n_policies,)
    max_regret: np.ndarray  # (n_policies,)
    best_loss: np.ndarray  # (n_sets,)


def analyse(losses, policies: list[str] | None = None, tol: float = 1e-9) -> Robustness:
    """Compute win-rate and regret for a ``(n_policies, n_sets)`` loss matrix."""
    L = np.asarray(losses, dtype=float)
    if L.ndim != 2:
        raise ValueError("losses must be 2-D (n_policies, n_sets)")
    best = L.min(axis=0)
    regret = L - best
    win_rate = (np.abs(regret) <= tol).mean(axis=1)
    return Robustness(
        win_rate=win_rate,
        mean_regret=regret.mean(axis=1),
        max_regret=regret.max(axis=1),
        best_loss=best,
    )


def to_markdown(rob: Robustness, policies: list[str]) -> str:
    lines = [
        "| Policy | Win rate | Mean regret | Max regret |",
        "|---|---|---|---|",
    ]
    for name, wr, mr, xr in zip(policies, rob.win_rate, rob.mean_regret, rob.max_regret):
        lines.append(f"| {name} | {wr:.2f} | {mr:.4g} | {xr:.4g} |")
    return "\n".join(lines)
