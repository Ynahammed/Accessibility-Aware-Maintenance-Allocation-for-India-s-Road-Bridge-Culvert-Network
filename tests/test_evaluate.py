import numpy as np
import pytest

from rra.evaluate import metrics, regret, stats


def test_log_loss_rewards_correct_confidence():
    perfect = np.array([[1.0, 0, 0, 0], [0, 0, 1.0, 0]])
    vague = np.array([[0.25, 0.25, 0.25, 0.25], [0.25, 0.25, 0.25, 0.25]])
    y = np.array([0, 2])
    assert metrics.log_loss(y, perfect) < metrics.log_loss(y, vague)


def test_rps_ordering():
    y = np.array([0, 1])
    good = np.array([[0.9, 0.1, 0, 0], [0, 0.9, 0.1, 0]])
    bad = np.array([[0, 0, 0, 1.0], [1.0, 0, 0, 0]])
    assert metrics.ranked_probability_score(y, good) < metrics.ranked_probability_score(y, bad)


def test_concordance_index_perfect_and_reversed():
    times = np.array([1.0, 2.0, 3.0])
    events = np.array([1, 1, 1])
    perfect = np.array([3.0, 2.0, 1.0])  # higher score = earlier event
    reversed_ = np.array([1.0, 2.0, 3.0])
    assert metrics.concordance_index(times, perfect, events) == pytest.approx(1.0)
    assert metrics.concordance_index(times, reversed_, events) == pytest.approx(0.0)


def test_access_lost_per_crore():
    assert metrics.access_lost_per_crore(500.0, 10.0) == pytest.approx(50.0)
    assert metrics.access_lost_per_crore(500.0, 0.0) == float("inf")


def test_regret_win_rate_and_gap():
    # 3 policies, 4 assumption sets; policy 1 is best everywhere
    losses = np.array(
        [
            [10.0, 12.0, 11.0, 13.0],
            [8.0, 9.0, 7.0, 10.0],  # best in all sets
            [20.0, 20.0, 20.0, 20.0],
        ]
    )
    rob = regret.analyse(losses)
    assert rob.win_rate[1] == 1.0
    assert rob.mean_regret[1] == 0.0
    assert rob.max_regret[0] == 4.0  # worst gap for policy 0: 11 - 7
    assert "Policy" in regret.to_markdown(rob, ["a", "b", "c"])


def test_paired_bootstrap_ci_sign():
    rng = np.random.default_rng(0)
    a = rng.normal(1.0, 0.5, size=200)
    b = rng.normal(0.0, 0.5, size=200)
    res = stats.paired_bootstrap_ci(a, b, n=2000)
    assert res.lo > 0  # a - b clearly positive
    assert res.mean > 0


def test_paired_bootstrap_requires_equal_shape():
    with pytest.raises(ValueError):
        stats.paired_bootstrap_ci([1, 2, 3], [1, 2])
