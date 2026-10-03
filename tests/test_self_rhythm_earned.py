# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import inspect
import io
import math
import tokenize

import pytest

pytest.importorskip("snntorch")

from kaine.oscillator.module_oscillator import (
    NEUTRAL_PHASE,
    SelfRhythmOscillator,
    make_self_rhythm_oscillator,
)


def test_deterministic_rate_histories() -> None:
    osc1 = make_self_rhythm_oscillator(seed=42, eta=0.0)
    osc2 = make_self_rhythm_oscillator(seed=42, eta=0.0)
    assert osc1 is not None and osc2 is not None
    for i in range(200):
        ext = 0.2 if i % 20 < 10 else 0.0
        osc1.step(0.3, external_drive=ext)
        osc2.step(0.3, external_drive=ext)
    assert osc1.rate_history() == osc2.rate_history()
    assert osc1.tau_rec == pytest.approx(osc2.tau_rec)


@pytest.mark.parametrize(
    "override",
    [
        {"tau_rec": 0.2, "tau_min": 0.3},  # tau_rec < tau_min
        {"tau_rec": 2.5, "tau_max": 2.0},  # tau_rec > tau_max
        {"tau_min": -0.1, "tau_rec": 0.8},  # non-positive tau_min
        {"plasticity_sign": 0.0},
        {"plasticity_sign": -2.0},
        {"afferent_gain": 1.5},
        {"phase_band_hz": (0.3, 15.0)},  # hi above Nyquist at 20 Hz
        {"phase_band_hz": (2.0, 0.3)},  # inverted band
        {"phase_band_hz": (-0.1, 1.0)},  # non-positive lo
        {"step_hz": float("inf")},
    ],
)
def test_constructor_validation(override: dict) -> None:
    kwargs = {"seed": 0}
    kwargs.update(override)
    with pytest.raises(ValueError):
        SelfRhythmOscillator(**kwargs)


def test_adaptation_off_tau_unchanged() -> None:
    osc = make_self_rhythm_oscillator(seed=1, eta=0.0)
    assert osc is not None
    tau0 = osc.tau_rec
    for i in range(2000):
        ext = 0.1 if i % 20 < 10 else 0.0
        osc.step(0.3, external_drive=ext)
    assert osc.tau_rec == pytest.approx(tau0)


def test_adaptation_on_changes_tau_within_bounds() -> None:
    osc = make_self_rhythm_oscillator(
        seed=2, eta=1.0, plasticity_sign=1.0, tau_min=0.3, tau_max=2.0
    )
    assert osc is not None
    tau0 = osc.tau_rec
    for i in range(4000):
        ext = 0.5 * (1.0 + math.sin(2.0 * math.pi * 0.8 * i / 20.0))
        osc.step(0.3, external_drive=ext)
    assert not math.isclose(osc.tau_rec, tau0, rel_tol=1e-4, abs_tol=1e-4)
    assert 0.3 <= osc.tau_rec <= 2.0


def test_no_external_drive_means_no_adaptation() -> None:
    osc = make_self_rhythm_oscillator(seed=3, eta=1.0)
    assert osc is not None
    tau0 = osc.tau_rec
    for _ in range(500):
        osc.step(0.3, external_drive=None)
    assert osc.tau_rec == pytest.approx(tau0)


def test_v2_serialization_roundtrip() -> None:
    osc1 = make_self_rhythm_oscillator(seed=4, eta=0.1)
    assert osc1 is not None
    for i in range(100):
        ext = 0.2 if i % 10 < 5 else 0.0
        osc1.step(0.3, external_drive=ext)

    state = osc1.serialize()
    assert state.get("kind") == "self_rhythm"
    assert state.get("version") == 2

    osc2 = make_self_rhythm_oscillator(seed=999, eta=0.1)
    assert osc2 is not None
    osc2.deserialize(state)

    assert osc2.tau_rec == pytest.approx(osc1.tau_rec)
    assert osc2.synaptic_resource == pytest.approx(osc1.synaptic_resource)
    assert osc2.step_count == osc1.step_count
    assert osc2.spike_sum == pytest.approx(osc1.spike_sum)

    for i in range(100):
        ext = 0.15 if i % 7 < 4 else 0.0
        osc1.step(0.3, external_drive=ext)
        osc2.step(0.3, external_drive=ext)

    assert osc2.rate_history() == osc1.rate_history()
    assert osc2.tau_rec == pytest.approx(osc1.tau_rec)


def test_v1_state_is_ignored() -> None:
    osc = make_self_rhythm_oscillator(seed=5, eta=0.0)
    assert osc is not None
    initial_tau = osc.tau_rec
    osc.deserialize(
        {"kind": "self_rhythm", "spike_rate_history": [0.1, 0.2, 0.3]}
    )
    assert osc.tau_rec == pytest.approx(initial_tau)
    assert osc.synaptic_resource == pytest.approx(1.0)
    assert osc.step_count == 0


def test_no_maternal_rate_constants_in_source() -> None:
    source = inspect.getsource(SelfRhythmOscillator)
    text_parts: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        text_parts.append(tok.string)
    text = " ".join(text_parts)
    for forbidden in ("70", "1.16", "1.17", "bpm", "heartbeat"):
        assert forbidden not in text, (
            f"{forbidden!r} found in SelfRhythmOscillator source "
            "outside comments/docstrings"
        )


def test_phase_and_amplitude_thresholds() -> None:
    osc = make_self_rhythm_oscillator(seed=6, eta=0.0)
    assert osc is not None
    step_hz = 20.0
    before_steps = int(3.9 * step_hz)
    after_steps = int(5.0 * step_hz) + 50

    for _ in range(before_steps):
        osc.step(0.3, external_drive=None)

    assert osc.phase() == NEUTRAL_PHASE
    assert osc.amplitude() == 0.0

    for _ in range(after_steps - before_steps):
        osc.step(0.3, external_drive=None)

    ph = osc.phase()
    assert math.isfinite(ph)
    assert ph != NEUTRAL_PHASE

    amp = osc.amplitude()
    assert math.isfinite(amp)
    assert amp >= 0.0
