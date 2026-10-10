# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import numpy as np
import pytest

from kaine.cycle.gestation import (
    GestationReadoutConfig,
    band_phase,
    beat_frequency,
    entrainment_plv,
    frequency_pull,
    withdrawn_frequency,
)

SAMPLE_HZ = 10.0
LOW_HZ = 0.3
HIGH_HZ = 2.0
TRIM_SAMPLES = 20


def _phase_series(freq, duration):
    t = np.arange(int(duration * SAMPLE_HZ)) / SAMPLE_HZ
    return t, 2.0 * np.pi * freq * t


def test_entrainment_plv_synchrony_beats_surrogates():
    duration = 300.0
    t, beat = _phase_series(1.17, duration)
    activity = np.cos(beat)
    surr1 = np.mod(_phase_series(1.05, duration)[1], 2.0 * np.pi)
    surr2 = np.mod(_phase_series(1.30, duration)[1], 2.0 * np.pi)
    plv, surrogate_max = entrainment_plv(
        activity, beat, [surr1, surr2], SAMPLE_HZ, LOW_HZ, HIGH_HZ, TRIM_SAMPLES
    )
    assert plv is not None
    assert plv > 0.9
    assert surrogate_max is not None
    assert surrogate_max < 0.3
    assert plv > surrogate_max


def test_entrainment_plv_detuned_activity_is_low():
    duration = 300.0
    t, beat = _phase_series(1.17, duration)
    activity = np.cos(2.0 * np.pi * 0.73 * t)
    plv, _ = entrainment_plv(
        activity, beat, [], SAMPLE_HZ, LOW_HZ, HIGH_HZ, TRIM_SAMPLES
    )
    assert plv is not None
    assert plv < 0.2


def test_withdrawn_frequency_matches_signal():
    duration = 20.0
    t = np.arange(int(duration * SAMPLE_HZ)) / SAMPLE_HZ
    activity = np.cos(2.0 * np.pi * 0.9 * t)
    f = withdrawn_frequency(t, activity, SAMPLE_HZ, LOW_HZ, HIGH_HZ)
    assert f is not None
    assert abs(f - 0.9) < 0.05


def test_beat_frequency_matches_phase_slope():
    duration = 300.0
    t, beat = _phase_series(1.17, duration)
    f = beat_frequency(t, beat)
    assert f is not None
    assert abs(f - 1.17) < 0.01


def test_frequency_pull():
    assert frequency_pull(1.15, 0.73, 1.17) > 0.9
    assert frequency_pull(0.75, 0.73, 1.17) is not None
    assert frequency_pull(0.75, 0.73, 1.17) < 0.1
    assert frequency_pull(1.15, 1.13, 1.17) is None


def test_config_rejects_entrainment_plv_floor():
    with pytest.raises(ValueError, match="Unknown keys"):
        GestationReadoutConfig.from_dict({"entrainment_plv_floor": 0.5})


def test_config_band_validation():
    with pytest.raises(ValueError):
        GestationReadoutConfig.from_dict(
            {"entrainment_band_low_hz": 1.5, "entrainment_band_high_hz": 0.5}
        )
    with pytest.raises(ValueError):
        GestationReadoutConfig.from_dict(
            {"sample_hz": 2.0, "entrainment_band_low_hz": 0.3, "entrainment_band_high_hz": 1.1}
        )


def test_config_edge_trim_validation():
    with pytest.raises(ValueError):
        GestationReadoutConfig.from_dict(
            {"entrainment_window_seconds": 10.0, "edge_trim_seconds": 5.0}
        )


def test_config_frequency_pull_floor_validation():
    with pytest.raises(ValueError):
        GestationReadoutConfig.from_dict({"frequency_pull_floor": 1.1})


def test_band_phase_returns_none_for_short_input():
    assert band_phase(np.zeros(5), SAMPLE_HZ, LOW_HZ, HIGH_HZ, TRIM_SAMPLES) is None
