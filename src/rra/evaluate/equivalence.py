"""Equivalence testing for paired policy comparisons.

A confidence interval that contains zero is an absence of evidence, not evidence of
absence. If the paper wants to say two allocation rules are *practically the same*, that
is a different statistical claim, and it needs a margin fixed in advance.

This module implements the two one-sided test (TOST) form of that claim, plus the design
arithmetic a reader will ask for immediately: how many paired scenarios would this design
need to demonstrate equivalence at a given margin, and what is the smallest difference the
current design can detect at all?

All functions are pure and take arrays of paired differences, so they work for any
`(policy A - policy B)` comparison on common random numbers.

Interpretation rule used throughout the project: TOST is reported as evidence of
equivalence only when both one-sided tests reject. Otherwise the honest label is
"inconclusive at this margin and sample size", and the reported numbers are the achieved
interval and the sample size that would be required.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class EquivalenceResult:
    """One TOST result plus the design quantities that qualify it."""

    mean: float
    sd: float
    n: int
    margin: float
    alpha: float
    se: float
    ci_lo: float
    ci_hi: float
    p_lower: float
    p_upper: float
    p_tost: float
    equivalent: bool
    min_detectable_difference: float
    required_n: int
    power: float

    def as_dict(self) -> dict:
        return asdict(self)


def _clean(values) -> np.ndarray:
    arr = np.asarray(values, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        raise ValueError("no finite paired differences")
    return arr


def tost(
    differences,
    margin: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> EquivalenceResult:
    """Two one-sided tests for ``|mean| < margin`` on paired differences.

    ``margin`` is in the units of the differences (person-days for this project) and must
    be positive. The null hypotheses are ``mean <= -margin`` and ``mean >= +margin``; both
    must be rejected for equivalence to be claimed.

    With fewer than two observations the test is undefined, so the result is returned as
    not equivalent with ``nan`` p-values rather than raising: an experiment with one
    scenario has no equivalence evidence, which is the honest answer.
    """
    if not math.isfinite(margin) or margin <= 0:
        raise ValueError("margin must be a positive, finite number")
    diff = _clean(differences)
    n = int(diff.size)
    mean = float(diff.mean())
    sd = float(diff.std(ddof=1)) if n > 1 else float("nan")

    if n < 2 or not math.isfinite(sd):
        return EquivalenceResult(
            mean=mean, sd=sd, n=n, margin=float(margin), alpha=alpha, se=float("nan"),
            ci_lo=float("nan"), ci_hi=float("nan"), p_lower=float("nan"),
            p_upper=float("nan"), p_tost=float("nan"), equivalent=False,
            min_detectable_difference=float("nan"), required_n=0, power=power,
        )

    se = sd / math.sqrt(n)
    df = n - 1
    # Both tests are one-sided at alpha; the TOST p-value is the larger of the two.
    if se == 0.0:
        # every paired difference identical: equivalence is exact if inside the margin
        inside = abs(mean) < margin
        p_lower = 0.0 if mean > -margin else 1.0
        p_upper = 0.0 if mean < margin else 1.0
        ci_lo = ci_hi = mean
    else:
        p_lower = float(stats.t.sf((mean + margin) / se, df))
        p_upper = float(stats.t.cdf((mean - margin) / se, df))
        half = float(stats.t.ppf(1.0 - alpha / 2.0, df)) * se
        ci_lo, ci_hi = mean - half, mean + half

    p_tost = max(p_lower, p_upper)
    return EquivalenceResult(
        mean=mean,
        sd=sd,
        n=n,
        margin=float(margin),
        alpha=alpha,
        se=se,
        ci_lo=ci_lo,
        ci_hi=ci_hi,
        p_lower=p_lower,
        p_upper=p_upper,
        p_tost=p_tost,
        equivalent=bool(p_tost < alpha),
        min_detectable_difference=min_detectable_difference(sd, n, alpha),
        required_n=required_n(sd, margin, alpha=alpha, power=power),
        power=power,
    )


def min_detectable_difference(sd: float, n: int, alpha: float = 0.05) -> float:
    """Half-width of the two-sided CI: the smallest difference this design can resolve.

    This is the quantity that decides whether "not significantly different" means
    "small" or "unmeasured". A design whose minimum detectable difference is larger than
    the effect the paper cares about cannot support either a difference or an equivalence
    claim at that effect size.
    """
    if n < 2 or not math.isfinite(sd) or sd <= 0:
        return float("nan")
    return float(stats.t.ppf(1.0 - alpha / 2.0, n - 1) * sd / math.sqrt(n))


def required_n(sd: float, margin: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Paired sample size for TOST to reject at ``margin`` with the target power.

    Uses the normal approximation to the two one-sided tests,
    ``n = ((z_{1-alpha} + z_{power}) * sd / margin) ** 2``, rounded up and floored at 2.
    It is a design aid, not a promise: the achieved power also depends on where the true
    mean sits inside the margin.
    """
    if not math.isfinite(sd) or sd <= 0 or not math.isfinite(margin) or margin <= 0:
        return 0
    z_alpha = float(stats.norm.ppf(1.0 - alpha))
    z_power = float(stats.norm.ppf(power))
    return max(2, int(math.ceil(((z_alpha + z_power) * sd / margin) ** 2)))


def paired_summary(a, b, margin: float, alpha: float = 0.05) -> dict:
    """Paired difference, bootstrap CI, TOST and design quantities in one dict.

    The bootstrap CI is the interval the rest of the project reports; the TOST interval is
    t-based and slightly wider at small ``n``. Both are returned so a reader can see that
    the equivalence verdict is not an artefact of the interval method.
    """
    a = _clean(a)
    b = _clean(b)
    if a.shape != b.shape:
        raise ValueError("paired inputs must have equal length")
    diff = a - b
    boot = stats.paired_bootstrap_ci(diff, np.zeros_like(diff), rng=0)
    eq = tost(diff, margin, alpha=alpha)
    return {
        "mean_person_days": float(diff.mean()),
        "bootstrap_ci_lo": float(boot.lo),
        "bootstrap_ci_hi": float(boot.hi),
        "tost": eq.as_dict(),
    }
