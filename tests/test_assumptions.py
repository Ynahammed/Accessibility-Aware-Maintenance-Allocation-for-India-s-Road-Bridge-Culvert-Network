import numpy as np
import pytest

from rra.assumptions import AssumptionRegister, Parameter


def test_default_register_is_valid():
    reg = AssumptionRegister.default()
    assert len(reg.names()) >= 15
    # every default lies within its own range (enforced in __post_init__, re-checked here)
    for name, p in reg.parameters.items():
        assert p.low <= p.default <= p.high, name


def test_sampling_is_seed_reproducible():
    reg = AssumptionRegister.default()
    a = reg.sample(12345, n=3)
    b = reg.sample(12345, n=3)
    assert a == b


def test_different_seeds_give_different_draws():
    reg = AssumptionRegister.default()
    a = reg.sample(1)[0]
    b = reg.sample(2)[0]
    assert a != b


def test_sampled_values_stay_in_range():
    reg = AssumptionRegister.default()
    for draw in reg.sample(7, n=50):
        for name, value in draw.items():
            p = reg[name]
            assert p.low - 1e-9 <= value <= p.high + 1e-9, name


def test_point_values_are_the_defaults():
    reg = AssumptionRegister.default()
    assert reg.point_values() == {n: p.default for n, p in reg.parameters.items()}


def test_markdown_lists_every_parameter():
    reg = AssumptionRegister.default()
    md = reg.to_markdown()
    for name in reg.names():
        assert f"`{name}`" in md


def test_with_values_overrides_defaults_and_keeps_ranges():
    reg = AssumptionRegister.default()
    draw = reg.sample(0)[0]
    reg2 = reg.with_values(draw)
    for name, p in reg2.parameters.items():
        assert p.default == pytest.approx(draw[name])
        assert p.low <= p.default <= p.high
    # the original register is untouched
    assert reg["fragility_beta0"].default == -3.0


def test_parameter_rejects_bad_range():
    with pytest.raises(ValueError):
        Parameter("x", "u", 5.0, 1.0, 2.0, "assumed", "", "")


def test_parameter_rejects_out_of_range_default():
    with pytest.raises(ValueError):
        Parameter("x", "u", 0.0, 1.0, 5.0, "assumed", "", "")
