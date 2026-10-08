import numpy as np
import pytest

from rra.deterioration import conformal, markov
from rra.deterioration.gbm import GradientBoostingDeterioration
from rra.deterioration.survival import DiscreteTimeSurvival


def deteriorating_counts():
    counts = np.zeros((4, 4))
    for i in range(3):
        counts[i, i + 1] = 10.0  # strong upward (worsening) drift
    counts[3, 3] = 10.0
    return counts


# --- Markov --------------------------------------------------------------------------


def test_transition_counts_hand_check():
    counts = markov.transition_counts([[0, 1, 2], [0, 0, 1]])
    assert counts[0, 1] == 2  # from seq0 and seq1
    assert counts[1, 2] == 1
    assert counts[0, 0] == 1
    assert counts.sum() == 4


def test_fit_transition_matrix_is_row_stochastic():
    P = markov.fit_transition_matrix(deteriorating_counts())
    assert np.allclose(P.sum(axis=1), 1.0)
    assert np.all(P >= 0)


def test_bootstrap_reproducible_and_row_stochastic():
    counts = deteriorating_counts()
    a = markov.bootstrap_transition_matrices(counts, n=3, rng=7)
    b = markov.bootstrap_transition_matrices(counts, n=3, rng=7)
    assert all(np.allclose(x, y) for x, y in zip(a, b))
    for P in a:
        assert np.allclose(P.sum(axis=1), 1.0)


def test_forecast_distribution_sums_to_one_and_worsens():
    P = markov.fit_transition_matrix(deteriorating_counts())
    dist = markov.forecast_distribution([1, 0, 0, 0], P, steps=10)
    assert dist.shape == (11, 4)
    assert np.allclose(dist.sum(axis=1), 1.0)
    # probability of being Poor-or-worse is non-decreasing when drift is upward
    poor = dist[:, 2] + dist[:, 3]
    assert np.all(np.diff(poor) >= -1e-9)


def test_expected_time_to_poor_is_shorter_from_worse_state():
    P = markov.fit_transition_matrix(deteriorating_counts())
    from_good = markov.expected_time_to(P, [1, 0, 0, 0])
    from_poor = markov.expected_time_to(P, [0, 0, 1, 0])
    assert from_good > from_poor


def test_first_passage_distribution_shape_and_index_zero():
    P = markov.fit_transition_matrix(deteriorating_counts())
    dist = markov.first_passage_distribution(P, [1, 0, 0, 0], max_steps=30)
    assert dist[0] == 0.0
    assert 0.0 <= dist.sum() <= 1.0 + 1e-9


def test_age_class_markov_buckets():
    counts = markov.transition_counts_by_age(
        [([5, 15, 25], [0, 1, 2]), ([35, 45], [1, 2])],
        n_classes=3,
        class_width=10,
    )
    assert counts.shape == (3, 4, 4)
    matrices = np.stack([markov.fit_transition_matrix(counts[i]) for i in range(3)])
    acm = markov.AgeClassMarkov(matrices, class_width=10)
    assert np.array_equal(acm.matrix_for_age(5), matrices[0])
    assert np.array_equal(acm.matrix_for_age(15), matrices[1])
    assert np.array_equal(acm.matrix_for_age(999), matrices[2])  # clamped to last class


# --- GBM (M1) ------------------------------------------------------------------------


def test_gbm_learns_separable_next_state():
    rng = np.random.default_rng(0)
    X = np.column_stack([rng.normal(size=400)])
    y = np.where(X[:, 0] > 0, 3, 0)
    m = GradientBoostingDeterioration(n_estimators=30).fit(X, y)
    proba = m.predict_proba(X)
    assert proba.shape == (400, 4)
    assert np.allclose(proba.sum(axis=1), 1.0)
    assert (m.predict(X) == y).mean() > 0.9


# --- Survival (M2) -------------------------------------------------------------------


def test_survival_outputs_are_sane():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(120, 1))
    durations = rng.integers(1, 12, size=120)
    events = rng.integers(0, 2, size=120)
    m = DiscreteTimeSurvival(max_time=15).fit(X, durations, events)
    S = m.predict_survival(X)
    assert S.shape == (120, 16)
    assert np.allclose(S[:, 0], 1.0)
    assert np.all(np.diff(S, axis=1) <= 1e-9)  # non-increasing
    med = m.median_time(X)
    assert np.all((med >= 0) & (med <= 15))


# --- Conformal -----------------------------------------------------------------------


def test_split_conformal_coverage_close_to_target():
    rng = np.random.default_rng(0)
    calib = rng.normal(size=2000)
    conf = conformal.SplitConformal(np.abs(calib))
    test = rng.normal(size=20000)  # a point predictor of 0, true value = test
    lo, hi = conf.interval(0.0, alpha=0.1)
    cov = conf.coverage(test, lo, hi)
    assert abs(cov - 0.9) < 0.03
    with pytest.raises(ValueError):
        conf.quantile(1.5)


def test_class_conditional_conformal_falls_back_for_unseen_group():
    rng = np.random.default_rng(0)
    residuals = rng.normal(size=300)
    groups = np.array(["a"] * 150 + ["b"] * 150)
    cc = conformal.ClassConditionalConformal().fit(np.abs(residuals), groups)
    lo, hi = cc.interval(0.0, "a", alpha=0.2)
    assert lo < 0 < hi
    lo2, hi2 = cc.interval(0.0, "unseen", alpha=0.2)  # fallback path
    assert lo2 < 0 < hi2
