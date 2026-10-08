"""GEV rainfall fit and return levels (plan section 5.2).

Annual maxima of 1-day and 5-day rainfall per IMD 0.25-degree cell are fitted to a
Generalised Extreme Value distribution. Cells with short records are pooled with their
neighbours. Return levels for 2, 5, 10, 25, 50 and 100 years are reported.

``scipy.stats.genextreme`` uses the ``c = -k`` convention (Jenkinson): the shape stored
here is scipy's ``c``. Return level for period ``T`` is the ``1 - 1/T`` quantile.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

DEFAULT_RETURN_PERIODS = (2, 5, 10, 25, 50, 100)


@dataclass
class GEVFit:
    c: float
    loc: float
    scale: float
    n_years: int
    pooled_cells: tuple = ()

    def return_level(self, period: float) -> float:
        if period <= 1:
            raise ValueError(f"return period must exceed 1, got {period}")
        return float(stats.genextreme.ppf(1.0 - 1.0 / period, self.c, self.loc, self.scale))

    def return_levels(self, periods=DEFAULT_RETURN_PERIODS) -> dict:
        return {T: self.return_level(T) for T in periods}

    def cdf(self, x) -> np.ndarray:
        return stats.genextreme.cdf(x, self.c, self.loc, self.scale)

    def goodness_of_fit(self, data) -> float:
        """Kolmogorov–Smirnov p-value against the fitted distribution."""
        d = np.asarray(data, dtype=float)
        return float(stats.kstest(d, lambda x: self.cdf(x)).pvalue)

    @property
    def finite(self) -> bool:
        vals = list(self.return_levels().values())
        return all(np.isfinite(v) for v in vals)


def fit_gev(annual_maxima, pooled_cells: tuple = ()) -> GEVFit:
    """Fit a GEV to one cell's annual maxima."""
    data = np.asarray(annual_maxima, dtype=float)
    data = data[np.isfinite(data)]
    if data.size < 5:
        raise ValueError(f"need >=5 finite years to fit a GEV, got {data.size}")
    c, loc, scale = stats.genextreme.fit(data)
    return GEVFit(float(c), float(loc), float(scale), int(data.size), tuple(pooled_cells))


def fit_gev_per_cell(
    series: dict,
    min_years: int = 30,
    neighbors: dict | None = None,
) -> dict:
    """Fit every cell; pool neighbouring cells where the record is shorter than ``min_years``.

    ``series`` maps cell -> 1-D annual maxima. ``neighbors`` maps cell -> iterable of
    adjacent cells (defaults to none, i.e. short cells are fitted on their own record).
    """
    out: dict = {}
    for cell, data in series.items():
        finite = np.asarray(data, dtype=float)
        finite = finite[np.isfinite(finite)]
        if finite.size >= min_years:
            out[cell] = fit_gev(finite)
            continue
        pooled = [finite]
        pooled_cells = (cell,)
        for nb in ((neighbors or {}).get(cell) or []):
            nb_data = np.asarray(series.get(nb, []), dtype=float)
            nb_data = nb_data[np.isfinite(nb_data)]
            if nb_data.size:
                pooled.append(nb_data)
                pooled_cells += (nb,)
        out[cell] = fit_gev(np.concatenate(pooled), pooled_cells=pooled_cells)
    return out
