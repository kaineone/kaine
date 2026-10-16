# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>


import pytest

from kaine.modules.affect.regulation import (
    PassiveDecay,
    RegulationActivation,
    RegulationAdjustment,
    RegulationConfig,
    RegulationPolicy,
    ThreeTierRegulation,
)
from kaine.modules.affect.state import DimensionalState


def test_config_defaults_equal_table_a1():
    cfg = RegulationConfig()
    assert cfg.set_point == pytest.approx(0.5)
    assert cfg.reappraisal_fraction == pytest.approx(0.5)
    assert cfg.selection_bias == pytest.approx(0.2)
    assert cfg.bias_decay_s == pytest.approx(20.0)
    assert cfg.sustain_window_s == pytest.approx(30.0)


def test_config_defaults_explicit_match():
    assert RegulationConfig() == RegulationConfig(0.5, 0.5, 0.2, 20.0, 30.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"set_point": -0.1},
        {"reappraisal_fraction": 1.5},
        {"selection_bias": -0.1},
        {"bias_decay_s": 0},
        {"sustain_window_s": 0},
        {"set_point": float("nan")},
    ],
)
def test_config_invalid_values_raise(kwargs):
    defaults = {
        "set_point": 0.5,
        "reappraisal_fraction": 0.5,
        "selection_bias": 0.2,
        "bias_decay_s": 20.0,
        "sustain_window_s": 30.0,
    }
    defaults.update(kwargs)
    with pytest.raises(ValueError):
        RegulationConfig(**defaults)


def test_intensity_function():
    assert ThreeTierRegulation.intensity(-0.6, 0.3, 0.3) == pytest.approx(0.6)
    assert ThreeTierRegulation.intensity(0.1, 0.9, 0.3) == pytest.approx(0.6)
    assert ThreeTierRegulation.intensity(0.0, 0.2, 0.3) == pytest.approx(0.0)


def test_no_activation_below_set_point():
    reg = ThreeTierRegulation()
    for t in range(121):
        result = reg.update(now=float(t), intensity=0.49, negative=True)
        assert result is None
        assert not reg.in_episode


def test_no_activation_when_not_negative():
    reg = ThreeTierRegulation()
    for t in range(121):
        result = reg.update(now=float(t), intensity=0.8, negative=False)
        assert result is None
        assert not reg.in_episode


def test_escalation_through_tiers():
    reg = ThreeTierRegulation()
    activations = []
    for t in range(126):
        result = reg.update(now=float(t), intensity=0.8, negative=True)
        if result is not None:
            activations.append((t, result))

    assert len(activations) == 4
    assert activations[0] == (30, RegulationActivation(tier=1, episode_s=30.0, intensity=0.8, target_source=None))
    assert activations[1] == (60, RegulationActivation(tier=2, episode_s=60.0, intensity=0.8, target_source=None))
    assert activations[2] == (90, RegulationActivation(tier=3, episode_s=90.0, intensity=0.8, target_source=None))
    assert activations[3] == (120, RegulationActivation(tier=3, episode_s=120.0, intensity=0.8, target_source=None))


def test_episode_end_resets_clock():
    reg = ThreeTierRegulation()
    for t in range(41):
        result = reg.update(now=float(t), intensity=0.8, negative=True)
        if t == 30:
            assert result is not None
            assert result.tier == 1
        else:
            assert result is None

    reg.update(now=41.0, intensity=0.1, negative=True)
    assert not reg.in_episode

    activation = None
    for t in range(42, 73):
        result = reg.update(now=float(t), intensity=0.8, negative=True)
        if result is not None:
            activation = result

    assert activation is not None
    assert activation.tier == 1
    assert activation.episode_s == pytest.approx(30.0)


def test_sparse_updates_emit_single_highest_tier():
    reg = ThreeTierRegulation()
    assert reg.update(now=0.0, intensity=0.8, negative=True) is None
    result = reg.update(now=65.0, intensity=0.8, negative=True)
    assert result is not None
    assert result.tier == 2
    assert result.episode_s == pytest.approx(65.0)


def test_mass_accumulation_and_target_source():
    reg = ThreeTierRegulation()
    assert reg.update(now=0.0, intensity=0.8, negative=True) is None

    reg.observe_coalition([("vision", 0.7), ("audition", 0.5)], negative=True)
    reg.observe_coalition([("vision", 0.5)], negative=True)
    reg.observe_coalition([("audition", 5.0)], negative=False)
    assert reg.target_source() == "vision"

    activation = reg.update(now=30.0, intensity=0.8, negative=True)
    assert activation is not None
    assert activation.tier == 1
    assert activation.target_source == "vision"


def test_target_source_ties_go_alphabetically_first():
    reg = ThreeTierRegulation()
    reg.update(now=0.0, intensity=0.8, negative=True)
    reg._mass = {"b": 1.0, "a": 1.0}
    assert reg.target_source() == "a"


def test_mass_observed_before_episode_is_ignored():
    reg = ThreeTierRegulation()
    reg.observe_coalition([("vision", 10.0)], negative=True)
    assert reg.update(now=0.0, intensity=0.8, negative=True) is None
    assert reg.target_source() is None

    activation = reg.update(now=30.0, intensity=0.8, negative=True)
    assert activation is not None
    assert activation.target_source is None


def test_take_reappraisal_once_per_episode():
    reg = ThreeTierRegulation()
    assert reg.take_reappraisal() is False

    reg.update(now=0.0, intensity=0.8, negative=True)
    assert reg.take_reappraisal() is True
    assert reg.take_reappraisal() is False

    reg.update(now=1.0, intensity=0.1, negative=True)
    assert reg.take_reappraisal() is False

    reg.update(now=2.0, intensity=0.8, negative=True)
    assert reg.take_reappraisal() is True
    assert reg.take_reappraisal() is False


@pytest.mark.asyncio
async def test_suggest_returns_zero_adjustment():
    reg = ThreeTierRegulation()
    assert await reg.suggest(DimensionalState()) == RegulationAdjustment()
    assert isinstance(reg, RegulationPolicy)
    assert isinstance(PassiveDecay(), RegulationPolicy)


def test_non_finite_inputs_do_not_start_episode():
    reg = ThreeTierRegulation()
    assert reg.update(now=float("nan"), intensity=0.8, negative=True) is None
    assert not reg.in_episode

    assert reg.update(now=0.0, intensity=float("inf"), negative=True) is None
    assert not reg.in_episode

    assert reg.update(now=0.0, intensity=0.8, negative=True) is None
    assert reg.in_episode

    assert reg.update(now=float("nan"), intensity=0.8, negative=True) is None
    assert reg.in_episode
    assert reg._episode_start == pytest.approx(0.0)
