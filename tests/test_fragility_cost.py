import pytest

from rra.cost.interventions import Intervention, apply_condition, effect_of
from rra.cost.sor import ScheduleOfRates
from rra.fragility.fragility import FragilityParams, failure_probability


def params():
    return FragilityParams(beta0=-3.0, beta1=1.2, beta2=2.0)


def test_failure_probability_in_unit_interval():
    for c in range(4):
        for r in (0.5, 1.0, 3.0):
            p = failure_probability(c, r, params())
            assert 0.0 < p < 1.0


def test_failure_probability_monotone_in_condition_and_rain():
    # worse condition -> higher failure probability
    assert failure_probability(3, 1.0, params()) > failure_probability(0, 1.0, params())
    # more rain -> higher failure probability
    assert failure_probability(1, 5.0, params()) > failure_probability(1, 1.0, params())


def test_failure_probability_rejects_bad_ratio():
    with pytest.raises(ValueError):
        failure_probability(1, 0.0, params())


def test_apply_condition_reduces_severity():
    assert apply_condition(3, Intervention.MINOR) <= 3
    assert apply_condition(3, Intervention.MAJOR) < apply_condition(3, Intervention.MINOR)
    assert apply_condition(3, Intervention.REPLACE) == 0
    assert apply_condition(2, Intervention.NONE) == 2


def test_effect_fragility_factor_reduces():
    assert effect_of(Intervention.MAJOR).fragility_factor < effect_of(
        Intervention.MINOR
    ).fragility_factor


def test_schedule_of_rates_cost_and_labour():
    sor = ScheduleOfRates()
    assert sor.cost("culvert", Intervention.NONE) == 0.0
    assert sor.cost("culvert", Intervention.MAJOR) > sor.cost("culvert", Intervention.MINOR)
    assert sor.labour("major_bridge", Intervention.MAJOR) > 0
    with pytest.raises(KeyError):
        sor.cost("spaceship", Intervention.MINOR)


def test_costs_are_in_crore():
    sor = ScheduleOfRates()
    assert sor.cost("culvert", Intervention.MAJOR) == pytest.approx(0.08)
    assert sor.cost("major_bridge", Intervention.REPLACE) == pytest.approx(3.0)


def test_emergency_cost_premium():
    sor = ScheduleOfRates()
    planned = sor.cost("minor_bridge", Intervention.MAJOR)
    emergency = sor.emergency_cost("minor_bridge", Intervention.MAJOR, premium=1.8)
    assert emergency == pytest.approx(planned * 1.8)
