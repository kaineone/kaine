# SPDX-License-Identifier: LicenseRef-CAL-0.2
"""unit tests of the Soma wetware backend on the simulator."""
from __future__ import annotations

import os

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import math

import cl.sim as clsim  # noqa: E402
import pytest
from kaine_cl1.backends.soma import WetwareInteroceptiveModel
from kaine_cl1.substrate.broker import SubstrateBroker
from kaine_cl1.substrate.session import SubstrateConfig, SubstrateSession

_SOURCE = "kaine_cl1.substrate.sources:make_reference_culture"
_CONFIG = {"seed": 7, "baseline_hz": 2.0, "evoked_spikes": 16, "response_ms": 20.0}

STEADY = [0.2, 0.3, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0]


@pytest.fixture
def substrate():
    clsim.set_simulator_data_source(_SOURCE, config=_CONFIG)
    session = SubstrateSession(SubstrateConfig(accelerated_time=True, ticks_per_second=100))
    session.open()
    broker = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=6)
    territory = broker.allocate("soma", 12)
    broker.open(session.neurons)
    try:
        yield broker, territory
    finally:
        session.close()
        clsim.clear_simulator_data_source()


def test_first_step_error_is_zero_and_units_match(substrate):
    broker, territory = substrate
    model = WetwareInteroceptiveModel(broker, territory)
    assert model.units == 12
    assert model.feature_dim == 8
    assert model.step(STEADY) == 0.0
    second = model.step(STEADY)
    assert math.isfinite(second)
    assert second > 0.0


def test_wrong_length_raises(substrate):
    broker, territory = substrate
    model = WetwareInteroceptiveModel(broker, territory)
    with pytest.raises(ValueError):
        model.step([0.1] * 7)


def test_non_finite_feature_skips_the_tick(substrate, monkeypatch):
    broker, territory = substrate
    model = WetwareInteroceptiveModel(broker, territory)
    calls = [0]
    orig = broker.run_cognitive_tick

    def counting(*args, **kwargs):
        calls[0] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(broker, "run_cognitive_tick", counting)
    before_state = model.state_dict()
    model.step(STEADY)
    assert calls[0] == 1

    err = model.step([float("nan")] + [0.0] * 7)
    assert err == 0.0
    assert calls[0] == 1
    assert model.adaptation_steps == 0
    assert model.state_dict() == before_state


def test_suspension_freezes_adaptation(substrate):
    broker, territory = substrate
    model = WetwareInteroceptiveModel(broker, territory)
    for _ in range(3):
        model.step(STEADY)
    before = model.state_dict()
    n = model.adaptation_steps

    model.suspended = True
    for _ in range(5):
        model.step(STEADY)
    assert model.state_dict() == before
    assert model.adaptation_steps == n

    model.suspended = False
    for _ in range(5):
        model.step(STEADY)
    assert model.adaptation_steps == n + 5
    assert model.state_dict() != before


def test_load_excursion_raises_error(substrate):
    broker, territory = substrate
    model = WetwareInteroceptiveModel(broker, territory)
    errors = [model.step(STEADY) for _ in range(20)]

    excursion = STEADY.copy()
    excursion[0] = 0.9
    excursion_error = model.step(excursion)
    assert excursion_error > max(errors[5:])


def test_salience_matches_silicon():
    kaine_forward = pytest.importorskip("kaine.modules.soma.forward")
    cases = [
        (0.5, 0.1, 0.7, None),
        (5.0, 0.1, 0.7, None),
        (float("nan"), 0.1, 0.7, None),
        (-1.0, 0.1, 0.7, None),
        (0.4, 0.1, 0.7, [0.2, 0.2]),
        (0.4, 0.1, 0.7, [0.0, 0.0]),
        (0.1, 0.1, 0.7, [0.3, 0.5]),
    ]

    for raw, baseline, alert, window in cases:
        wet = WetwareInteroceptiveModel.prediction_error_to_salience(
            None, raw, baseline, alert, error_window=window
        )
        silicon = kaine_forward.SubstrateForwardModel.prediction_error_to_salience(
            None, raw, baseline, alert, error_window=window
        )
        assert wet == pytest.approx(silicon)


def test_state_dict_round_trip_and_shape_check(substrate):
    broker, territory = substrate
    model = WetwareInteroceptiveModel(broker, territory)
    for _ in range(4):
        model.step(STEADY)
    state = model.state_dict()

    model2 = WetwareInteroceptiveModel(broker, territory)
    model2.load_state_dict(state)
    assert model2.state_dict() == state

    bad = {"weight": [[0.0] * 32] * 8, "bias": [0.0] * 8}
    with pytest.raises(ValueError):
        model.load_state_dict(bad)
    assert model.state_dict() == state

    nan_state = {"weight": [row[:] for row in state["weight"]], "bias": state["bias"][:]}
    nan_state["weight"][0][0] = float("nan")
    with pytest.raises(ValueError):
        model.load_state_dict(nan_state)
    assert model.state_dict() == state

