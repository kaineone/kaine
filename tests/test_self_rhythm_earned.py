import inspect
import math
import tokenize
from io import BytesIO

import numpy as np
import pytest
from scipy.signal import welch

pytest.importorskip("snntorch")

from kaine.oscillator.module_oscillator import (
    NEUTRAL_PHASE,
    SelfRhythmOscillator,
    make_self_rhythm_oscillator,
)

STEP_HZ = 20.0


def _run_steps(osc, n, own=0.4, external=None):
    for _ in range(n):
        osc.step(own, external_drive=external)


def _dominant_freq(activity, fs=STEP_HZ):
    nperseg = min(len(activity), 1200)
    f, P = welch(activity, fs=fs, nperseg=nperseg)
    P[0] = 0.0
    return float(f[np.argmax(P)])


def test_factory_builds():
    osc = make_self_rhythm_oscillator(seed=0)
    assert isinstance(osc, SelfRhythmOscillator)


def test_determinism_fixed_seed():
    a = SelfRhythmOscillator(seed=123)
    b = SelfRhythmOscillator(seed=123)
    _run_steps(a, 400)
    _run_steps(b, 400)
    assert a.activity_history() == b.activity_history()
    assert a.rate_history() == b.rate_history()
    assert a.tau_rec == pytest.approx(b.tau_rec)


def test_constructor_validation():
    base = {"seed": 0}
    with pytest.raises(ValueError):
        SelfRhythmOscillator(tau_rec=0.5, tau_min=0.9, tau_max=3.0, **base)
    with pytest.raises(ValueError):
        SelfRhythmOscillator(tau_rec=4.0, tau_min=0.9, tau_max=3.0, **base)
    with pytest.raises(ValueError):
        SelfRhythmOscillator(tau_rec=1.6, tau_min=2.0, tau_max=3.0, **base)
    with pytest.raises(ValueError):
        SelfRhythmOscillator(plasticity_sign=2.0, **base)
    with pytest.raises(ValueError):
        SelfRhythmOscillator(afferent_gain=1.1, **base)
    with pytest.raises(ValueError):
        SelfRhythmOscillator(
            step_hz=20.0, phase_band_hz=(0.3, 15.0), **base
        )
    with pytest.raises(ValueError):
        SelfRhythmOscillator(substeps=0, **base)


def test_undriven_rhythm_in_band():
    osc = SelfRhythmOscillator(seed=42)
    n = int(120.0 * STEP_HZ)
    _run_steps(osc, n, own=0.4, external=None)
    activity = np.asarray(osc.activity_history())
    f_dom = _dominant_freq(activity)
    # Fetal breathing band (Natale et al. 1988: about 30-70 breaths/min).
    assert 0.5 <= f_dom <= 1.0
    assert np.std(activity) > 0.05


def test_frequency_decreases_with_tau_rec():
    n = int(120.0 * STEP_HZ)
    osc_fast = SelfRhythmOscillator(seed=1, tau_rec=1.2)
    osc_slow = SelfRhythmOscillator(seed=1, tau_rec=2.2)
    _run_steps(osc_fast, n, own=0.4)
    _run_steps(osc_slow, n, own=0.4)
    f_fast = _dominant_freq(np.asarray(osc_fast.activity_history()))
    f_slow = _dominant_freq(np.asarray(osc_slow.activity_history()))
    assert f_fast > f_slow


def test_eta_adaptation_bounds():
    n = int(60.0 * STEP_HZ)
    step_period = int(STEP_HZ / 0.5)

    # eta=0 -> tau_rec stays at its initial value.
    osc_zero = SelfRhythmOscillator(seed=2, eta=0.0, tau_rec=1.6)
    for i in range(n):
        ext = 0.5 + 0.5 * math.sin(2.0 * math.pi * i / step_period)
        osc_zero.step(0.4, external_drive=ext)
    assert osc_zero.tau_rec == pytest.approx(1.6)

    # eta>0 with periodic drive -> tau_rec moves but stays within bounds.
    osc_adapt = SelfRhythmOscillator(
        seed=2, eta=0.01, plasticity_sign=-1.0, tau_rec=1.6
    )
    for i in range(n):
        ext = 0.5 + 0.5 * math.sin(2.0 * math.pi * i / step_period)
        osc_adapt.step(0.4, external_drive=ext)
    assert osc_adapt.tau_rec != pytest.approx(1.6, abs=1e-4)
    assert 0.9 <= osc_adapt.tau_rec <= 3.0

    # eta>0 but external_drive=None -> no adaptation.
    osc_none = SelfRhythmOscillator(
        seed=2, eta=0.01, plasticity_sign=-1.0, tau_rec=1.6
    )
    _run_steps(osc_none, n, own=0.4, external=None)
    assert osc_none.tau_rec == pytest.approx(1.6)


def test_serialization_v2_roundtrip():
    original = SelfRhythmOscillator(seed=7)
    _run_steps(original, 100, own=0.4)

    state = original.serialize()
    assert state.get("version") == 2

    restored = SelfRhythmOscillator(seed=999)
    restored.deserialize(state)

    n = 200
    for i in range(n):
        ext = 0.3 * math.sin(2.0 * math.pi * i / STEP_HZ)
        original.step(0.4, external_drive=ext)
        restored.step(0.4, external_drive=ext)

    assert np.allclose(original.activity_history(), restored.activity_history())
    assert np.allclose(original.rate_history(), restored.rate_history())
    assert original.tau_rec == pytest.approx(restored.tau_rec)


def test_serialization_v1_ignored():
    a = SelfRhythmOscillator(seed=5)
    b = SelfRhythmOscillator(seed=5)
    v1_state = {"version": 1, "kind": "lif"}
    a.deserialize(v1_state)
    _run_steps(a, 50, own=0.4)
    _run_steps(b, 50, own=0.4)
    assert a.activity_history() == b.activity_history()
    assert a.rate_history() == b.rate_history()


def test_no_maternal_rate_constant():
    source = inspect.getsource(SelfRhythmOscillator)
    forbidden = {"70", "1.16", "1.17", "bpm", "heartbeat"}
    tokens = []
    for tok in tokenize.tokenize(BytesIO(source.encode("utf-8")).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        tokens.append(tok.string)
    found = {t.lower() for t in tokens if t.lower() in forbidden}
    assert not found, f"forbidden maternal-rate tokens found: {found}"


def test_phase_and_amplitude_progression():
    osc = SelfRhythmOscillator(seed=3)
    _run_steps(osc, int(3.0 * STEP_HZ), own=0.4)
    assert osc.phase() == NEUTRAL_PHASE
    assert osc.amplitude() == 0.0

    _run_steps(osc, int(7.0 * STEP_HZ), own=0.4)
    ph = osc.phase()
    amp = osc.amplitude()
    assert ph != NEUTRAL_PHASE
    assert math.isfinite(ph)
    assert amp > 0.0
    assert math.isfinite(amp)
