# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the pure maternal-channel signal module."""
from __future__ import annotations

import random

import numpy as np
import pytest

from kaine.modules.perception_prng import keyed_u64 as _keyed_u64
from kaine.modules.perception_prng import unit_float as _unit_float
from kaine.modules.womb_signal import (
    MATERNAL_HEARTBEAT_GAIN,
    SEED_SALT_AUDIO,
    SEED_SALT_VIDEO,
    WombParams,
    _heartbeat_integral,
    beat_pulse,
    colour_saturation,
    flow_phase,
    heartbeat_phase,
    lowpassed_noise,
    maternal_hue,
    maternal_state,
)


def test_params_defaults() -> None:
    p = WombParams.from_sections(None, None, None)
    assert p.heartbeat_bpm == 70.0
    assert p.heartbeat_drift == 0.03
    assert p.maternal_state_rate == 0.02
    assert p.maternal_state_drives_heartbeat is True
    assert p.maternal_distress_excursions is False
    assert p.external_drive_to_self_rhythm is True
    assert p.external_drive_max_amplitude == 0.4
    assert p.luminance_mean == 0.15
    assert p.luminance_contrast == 0.10
    assert p.luminance_pulse_depth == 0.35
    assert p.maternal_state_hue_gain == 0.6
    assert p.colour_ramp_seconds == 3600.0
    assert p.lowpass_hz == 500.0


def test_params_unknown_key_rejected() -> None:
    with pytest.raises(ValueError, match="unknown .* config keys"):
        WombParams.from_sections({"not_a_key": 1}, None, None)


def test_params_distress_excursions_rejected() -> None:
    with pytest.raises(ValueError, match="maternal distress excursions are not built yet"):
        WombParams.from_sections({"maternal_distress_excursions": True}, None, None)


def test_params_bool_fields_must_be_bool() -> None:
    with pytest.raises(ValueError, match="maternal_state_drives_heartbeat must be a bool"):
        WombParams.from_sections({"maternal_state_drives_heartbeat": "true"}, None, None)


def test_params_numeric_fields_must_not_be_bool() -> None:
    with pytest.raises(ValueError, match="heartbeat_bpm must be a number, not a bool"):
        WombParams.from_sections({"heartbeat_bpm": True}, None, None)


@pytest.mark.parametrize(
    ("table", "key", "bad_value"),
    [
        ("womb", "heartbeat_bpm", 39),
        ("womb", "heartbeat_bpm", 121),
        ("womb", "heartbeat_drift", -0.01),
        ("womb", "heartbeat_drift", 0.21),
        ("womb", "maternal_state_rate", 0.0),
        ("womb", "maternal_state_rate", 1.1),
        ("video", "luminance_mean", 0.0),
        ("video", "luminance_mean", 0.51),
        ("video", "luminance_contrast", -0.1),
        ("video", "luminance_contrast", 0.51),
        ("video", "luminance_pulse_depth", -0.1),
        ("video", "luminance_pulse_depth", 1.1),
        ("video", "maternal_state_hue_gain", -0.1),
        ("video", "maternal_state_hue_gain", 1.1),
        ("video", "colour_ramp_seconds", 0.0),
        ("video", "colour_ramp_seconds", -1.0),
        ("audio", "lowpass_hz", 50.0),
        ("audio", "lowpass_hz", 2001.0),
        ("womb", "external_drive_max_amplitude", -0.1),
        ("womb", "external_drive_max_amplitude", 1.1),
        ("womb", "maternal_distress_max_magnitude", 1.1),
        ("womb", "maternal_distress_max_seconds", 0.0),
    ],
)
def test_params_range_rejected(table: str, key: str, bad_value: float) -> None:
    sections: dict[str, dict[str, object] | None] = {"womb": None, "video": None, "audio": None}
    sections[table] = {key: bad_value}
    with pytest.raises(ValueError, match="outside allowed range"):
        WombParams.from_sections(sections["womb"], sections["video"], sections["audio"])


def test_params_key_in_wrong_table_rejected() -> None:
    with pytest.raises(ValueError):
        WombParams.from_sections({"luminance_mean": 0.15}, None, None)
    with pytest.raises(ValueError):
        WombParams.from_sections(None, {"lowpass_hz": 500.0}, None)
    with pytest.raises(ValueError):
        WombParams.from_sections(None, None, {"heartbeat_bpm": 70.0})


def test_maternal_state_bounds_and_reproducibility() -> None:
    params = WombParams()
    rng = random.Random(0x1234)
    max_delta_v = 0.0
    max_delta_a = 0.0
    for _ in range(10_000):
        t = rng.uniform(0.0, 1_000_000.0)
        v, a = maternal_state(0, t, params)
        assert -1.0 <= v <= 1.0
        assert 0.0 <= a <= 1.0

        v2, a2 = maternal_state(0, t, params)
        assert (v, a) == (v2, a2)

        v3, a3 = maternal_state(1, t, params)
        assert (v, a) != pytest.approx((v3, a3), abs=1e-9)

        v1s, a1s = maternal_state(0, t + 1.0, params)
        max_delta_v = max(max_delta_v, abs(v1s - v))
        max_delta_a = max(max_delta_a, abs(a1s - a))

    assert max_delta_v < 0.02
    assert max_delta_a < 0.02


def test_heartbeat_phase_properties() -> None:
    params = WombParams()
    dt = 0.001
    t = np.arange(0.0, 600.0, dt)
    phases = heartbeat_phase(0, t, params)

    assert isinstance(phases, np.ndarray)
    assert np.all((phases >= 0.0) & (phases < 1.0))

    # Deterministic.
    assert np.allclose(phases, heartbeat_phase(0, t, params), atol=0.0)

    # Every wrap is one beat: the wrap count equals the whole beats elapsed.
    dphase = np.diff(phases)
    wraps = int(np.sum(dphase < -0.5))
    integral = _heartbeat_integral(0, np.array([0.0, 600.0]), params)
    assert wraps == int(np.floor(integral[1]) - np.floor(integral[0]))

    # rate/base = (1 + drift*sin)(1 + gain*S_a) with |S_a| <= 3, so the
    # instantaneous rate stays inside that analytic envelope and the mean
    # rate over any window does too.
    target = params.heartbeat_bpm / 60.0
    lo = target * (1.0 - params.heartbeat_drift) * (1.0 - 3 * MATERNAL_HEARTBEAT_GAIN)
    hi = target * (1.0 + params.heartbeat_drift) * (1.0 + 3 * MATERNAL_HEARTBEAT_GAIN)
    assert lo <= wraps / 600.0 <= hi + 1.0 / 600.0
    dphase[dphase < 0.0] += 1.0
    inst_rate = dphase / dt
    assert np.all((inst_rate >= lo * (1 - 1e-6)) & (inst_rate <= hi * (1 + 1e-6)))


def test_beat_pulse_shape() -> None:
    assert 0.0 <= beat_pulse(0.0) <= 1.0
    assert beat_pulse(0.0) == 1.0
    assert beat_pulse(0.5) < beat_pulse(0.0)
    assert beat_pulse(0.12) > beat_pulse(0.5)
    assert beat_pulse(1.0) == pytest.approx(beat_pulse(0.0), abs=1e-12)


def test_beat_pulse_vectorised() -> None:
    arr = np.array([0.0, 0.5, 0.12, 1.0])
    out = beat_pulse(arr)
    assert isinstance(out, np.ndarray)
    assert out[0] == 1.0
    assert np.allclose(
        out, np.array([beat_pulse(float(x)) for x in arr]), atol=0.0
    )


def test_colour_saturation() -> None:
    params = WombParams()
    assert colour_saturation(0.0, params) == 0.0
    assert colour_saturation(-1.0, params) == 0.0
    assert colour_saturation(float("inf"), params) == 0.0
    assert colour_saturation(float("nan"), params) == 0.0

    prev = 0.0
    for lived in (1.0, 10.0, 100.0, 1000.0, 10_000.0):
        s = colour_saturation(lived, params)
        assert 0.0 <= s < 1.0
        assert s > prev
        prev = s

    tau = params.colour_ramp_seconds
    assert colour_saturation(3.0 * tau, params) > 0.9


def test_flow_phase_properties() -> None:
    params = WombParams()
    t = np.array([0.0, 1.0, 1e3, 1e6, 1e7], dtype=np.float64)
    phases = flow_phase(0, t, params)
    assert isinstance(phases, np.ndarray)
    assert np.all((phases >= 0.0) & (phases < 1.0))
    assert np.allclose(phases, flow_phase(0, t, params), atol=0.0)

    # Central difference with a step wide enough that float64 rounding of the
    # ~1e5-cycle integral (before the mod) stays far below the tolerance.
    t0 = 1e6
    dt = 1e-2
    p0 = float(flow_phase(0, t0 - dt, params))
    p1 = float(flow_phase(0, t0 + dt, params))
    diff = (p1 - p0) % 1.0
    derivative = diff / (2.0 * dt)

    flow_base = 0.01 + 0.03 * _unit_float(
        _keyed_u64(0, 0, SEED_SALT_VIDEO | 0x14)
    )
    _, arousal = maternal_state(0, t0, params)
    target = flow_base * (1.0 + 2.0 * arousal)
    assert derivative == pytest.approx(target, rel=1e-6)


def test_maternal_hue() -> None:
    assert maternal_hue(1.0) == pytest.approx(0.12, abs=1e-12)
    assert maternal_hue(0.0) == pytest.approx(0.48, abs=1e-12)
    assert maternal_hue(-1.0) == pytest.approx(0.94, abs=1e-12)
    assert maternal_hue(float("nan")) == pytest.approx(0.48, abs=1e-12)
    assert maternal_hue(-1.0) > maternal_hue(0.0) > maternal_hue(1.0)
    assert len({maternal_hue(-1.0), maternal_hue(0.0), maternal_hue(1.0)}) == 3


def _white_block(seed: int, block_index: int, n: int) -> np.ndarray:
    from kaine.modules.perception_prng import keyed_u64

    rng = np.random.Philox(
        key=keyed_u64(seed, block_index, SEED_SALT_AUDIO | 0x30)
    )
    raw = rng.random_raw(n)
    return (raw >> np.uint64(11)).astype(np.float64) / float(1 << 53) - 0.5


def test_lowpassed_noise_deterministic_and_validation() -> None:
    from kaine.modules.womb_signal import _LOWPASS_TAPS

    params = WombParams()
    n = 480
    a = lowpassed_noise(7, 3, n, 16000.0, params.lowpass_hz)
    b = lowpassed_noise(7, 3, n, 16000.0, params.lowpass_hz)
    assert a.shape == (n,)
    assert np.allclose(a, b, atol=0.0)

    with pytest.raises(ValueError):
        lowpassed_noise(7, 3, _LOWPASS_TAPS - 2, 16000.0, params.lowpass_hz)
    with pytest.raises(ValueError):
        lowpassed_noise(7, 3, n, 16000.0, 9000.0)
    with pytest.raises(ValueError):
        lowpassed_noise(7, 3, n, 16000.0, 0.0)


def test_lowpassed_noise_continuous_across_blocks() -> None:
    from kaine.modules.womb_signal import _LOWPASS_TAPS

    seed = 11
    sr = 16000.0
    lp = 500.0
    n = 480
    L = _LOWPASS_TAPS - 1
    k = 5

    b_k = lowpassed_noise(seed, k, n, sr, lp)
    b_k1 = lowpassed_noise(seed, k + 1, n, sr, lp)
    concat_out = np.concatenate([b_k, b_k1])

    prefix = _white_block(seed, k - 1, n)[-L:]
    wk = _white_block(seed, k, n)
    wk1 = _white_block(seed, k + 1, n)
    big = np.concatenate([prefix, wk, wk1])

    nn = np.arange(_LOWPASS_TAPS, dtype=np.float64)
    h = np.sinc(2.0 * (lp / sr) * (nn - (_LOWPASS_TAPS - 1) / 2.0))
    h *= np.hamming(_LOWPASS_TAPS)
    h /= h.sum()
    ref = np.convolve(big, h, mode="valid") / np.sqrt(np.sum(h * h) / 12.0)

    assert np.allclose(concat_out, ref, atol=1e-12)


def test_lowpassed_noise_spectral_shape() -> None:

    params = WombParams()
    sr = 16000.0
    lp = params.lowpass_hz
    n = 480
    total_seconds = 4.0
    n_blocks = int(total_seconds * sr / n)
    chunks = [lowpassed_noise(3, k, n, sr, lp) for k in range(n_blocks)]
    signal = np.concatenate(chunks)
    assert len(signal) == n_blocks * n

    # Welch-ish averaged periodogram with Hann windows.
    window_size = 4096
    step = window_size
    hann = np.hanning(window_size)
    psd_sum = np.zeros(window_size // 2 + 1, dtype=np.float64)
    count = 0
    for start in range(0, len(signal) - window_size + 1, step):
        seg = signal[start : start + window_size] * hann
        fft = np.fft.rfft(seg)
        psd_sum += np.abs(fft) ** 2
        count += 1
    psd = psd_sum / count
    freqs = np.fft.rfftfreq(window_size, d=1.0 / sr)

    below_mask = freqs < 500.0
    above_mask = freqs > 1500.0
    assert np.mean(psd[below_mask]) > 0.0
    ratio = np.mean(psd[below_mask]) / np.mean(psd[above_mask])
    assert ratio >= 10 ** (30.0 / 10.0)

    band = (freqs >= 30.0) & (freqs <= 500.0)
    band_psd = psd[band]
    peak_to_median = band_psd.max() / np.median(band_psd)
    assert peak_to_median < 25.0
