# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.thymos.state import DimensionalState


def test_default_baseline():
    s = DimensionalState()
    assert s.valence == 0.0
    assert 0.0 <= s.arousal <= 1.0
    assert s.dominance == 0.0


def test_clamping_on_overflow():
    s = DimensionalState(valence=2.0, arousal=1.5, dominance=-5.0).clamped()
    assert s.valence == 1.0
    assert s.arousal == 1.0
    assert s.dominance == -1.0


def test_drift_toward_baseline():
    state = DimensionalState(valence=0.8, arousal=0.8, dominance=0.5)
    baseline = DimensionalState(valence=0.0, arousal=0.3, dominance=0.0)
    drifted = state.drift_toward(baseline, rate_per_s=0.5, dt=2.0)
    # Should be closer to baseline than the original.
    assert abs(drifted.valence) < abs(state.valence)
    assert abs(drifted.dominance) < abs(state.dominance)


def test_drift_with_zero_dt_is_noop():
    state = DimensionalState(valence=0.5)
    baseline = DimensionalState(valence=0.0)
    drifted = state.drift_toward(baseline, rate_per_s=1.0, dt=0.0)
    assert drifted.valence == state.valence


def test_drift_with_zero_rate_is_noop():
    state = DimensionalState(valence=0.5)
    baseline = DimensionalState(valence=0.0)
    drifted = state.drift_toward(baseline, rate_per_s=0.0, dt=10.0)
    assert drifted.valence == state.valence


def test_drift_eventually_converges():
    state = DimensionalState(valence=1.0)
    baseline = DimensionalState(valence=0.0)
    for _ in range(100):
        state = state.drift_toward(baseline, rate_per_s=0.5, dt=1.0)
    assert abs(state.valence) < 0.01


def test_nudged_clamps_and_increments():
    s = DimensionalState(valence=0.9, arousal=0.95)
    new = s.nudged(valence=0.5, arousal=0.5)
    assert new.valence == 1.0
    assert new.arousal == 1.0


def test_dataclass_is_frozen():
    s = DimensionalState()
    with pytest.raises(Exception):
        s.valence = 0.5  # type: ignore[misc]


def test_to_dict_serializes_floats():
    s = DimensionalState(valence=0.3, arousal=0.6, dominance=-0.2)
    d = s.to_dict()
    assert d == {"valence": 0.3, "arousal": 0.6, "dominance": -0.2}
