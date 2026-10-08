import numpy as np
import pytest

from rra.hazard import gev_fit, scenarios


def synthetic_maxima(seed=0, size=80):
    from scipy import stats

    rng = np.random.default_rng(seed)
    return stats.genextreme.rvs(-0.1, loc=120.0, scale=35.0, size=size, random_state=rng)


def test_return_levels_increase_with_period_and_are_finite():
    fit = gev_fit.fit_gev(synthetic_maxima())
    levels = fit.return_levels()
    periods = sorted(levels)
    values = [levels[t] for t in periods]
    assert all(np.isfinite(v) for v in values)
    assert fit.finite
    for a, b in zip(values, values[1:]):
        assert b > a  # strictly increasing


def test_return_period_must_exceed_one():
    fit = gev_fit.fit_gev(synthetic_maxima())
    with pytest.raises(ValueError):
        fit.return_level(1.0)


def test_short_record_is_pooled_with_neighbours():
    series = {
        "c0": synthetic_maxima(size=8),   # short
        "c1": synthetic_maxima(size=60),
        "c2": synthetic_maxima(size=60),
    }
    fits = gev_fit.fit_gev_per_cell(series, min_years=30, neighbors={"c0": ["c1", "c2"]})
    assert fits["c0"].pooled_cells == ("c0", "c1", "c2")
    assert fits["c0"].n_years == 8 + 60 + 60
    assert fits["c1"].pooled_cells == ()


def test_fit_needs_enough_years():
    with pytest.raises(ValueError):
        gev_fit.fit_gev([1.0, 2.0])


def test_resample_preserves_spatial_correlation():
    rng = np.random.default_rng(0)
    latent = rng.normal(size=200)
    cell0 = latent * 2.0 + rng.normal(scale=0.2, size=200)
    cell1 = latent * 1.5 + rng.normal(scale=0.2, size=200)
    fields = np.column_stack([cell0, cell1])
    orig_corr = np.corrcoef(fields.T)[0, 1]
    res = scenarios.resample_year_fields(fields, n=20000, rng=1)
    assert res.shape == (20000, 2)
    res_corr = np.corrcoef(res.T)[0, 1]
    assert abs(res_corr - orig_corr) < 0.1


def test_resample_is_seed_reproducible():
    fields = np.arange(12, dtype=float).reshape(3, 4)
    a = scenarios.resample_year_fields(fields, n=10, rng=5)
    b = scenarios.resample_year_fields(fields, n=10, rng=5)
    assert np.array_equal(a, b)


def test_stress_scaling_and_target():
    field = np.array([[10.0, 20.0]])
    assert np.allclose(scenarios.stress_scaled(field, 1.5), [[15.0, 30.0]])
    target = scenarios.stress_to_return_level(field, target_level=100.0, base_level=15.0)
    assert target.mean() == pytest.approx(100.0)
    with pytest.raises(ValueError):
        scenarios.stress_scaled(field, 0.0)
