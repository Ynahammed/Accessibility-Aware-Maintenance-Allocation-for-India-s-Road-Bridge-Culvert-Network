"""Paired statistics (plan section 6).

All policies are evaluated on the same scenario draws, so differences are *paired*:
resample scenarios (and, for cross-region claims, regions) with replacement and report
the bootstrap distribution of the paired difference.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class BootstrapResult:
    mean: float
    lo: float
    hi: float
    n: int


def paired_bootstrap_ci(
    a, b, n: int = 10000, alpha: float = 0.05, rng: np.random.Generator | int = 0
) -> BootstrapResult:
    """Bootstrap CI for ``mean(a - b)`` over paired samples (a, b share the draw)."""
    if isinstance(rng, (int, np.integer)):
        rng = np.random.default_rng(int(rng))
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("paired inputs must have equal shape")
    diff = a - b
    k = diff.size
    if k == 0:
        raise ValueError("no paired samples")
    idx = rng.integers(0, k, size=(n, k))
    boot = diff[idx].mean(axis=1)
    lo, hi = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    return BootstrapResult(mean=float(diff.mean()), lo=float(lo), hi=float(hi), n=n)


def medians_and_ranges(runs, axis: int = 0):
    """Median and (min, max) across seeds for a stack of runs."""
    arr = np.asarray(runs, dtype=float)
    return np.median(arr, axis=axis), arr.min(axis=axis), arr.max(axis=axis)
