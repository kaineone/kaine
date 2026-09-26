import math

import pytest

from kaine.oscillator.module_oscillator import (
    MIN_PLV_WINDOW,
    ModuleOscillator,
    SelfRhythmOscillator,
    make_self_rhythm_oscillator,
)

snntorch = pytest.importorskip("snntorch")


def test_self_rhythm_matches_module_oscillator_without_external_drive():
    seed = 42
    lif = ModuleOscillator(seed=seed)
    self_rhythm = SelfRhythmOscillator(seed=seed)
    for d in [0.0, 0.3, 0.7, 1.0, 0.0, 0.5]:
        lif.step(d)
        self_rhythm.step(d)
    assert list(lif._spike_rate_history) == list(self_rhythm._spike_rate_history)


def test_external_drive_changes_history():
    seed = 7
    a = SelfRhythmOscillator(seed=seed)
    b = SelfRhythmOscillator(seed=seed)
    for d in [0.2, 0.4, 0.6, 0.8, 0.3]:
        a.step(d)
        b.step(d, external_drive=0.5)
    assert list(a._spike_rate_history) != list(b._spike_rate_history)


def test_external_drive_clamping_and_nan():
    o_high = SelfRhythmOscillator(seed=1)
    o_high.step(0.0, external_drive=2.0)

    o_one = SelfRhythmOscillator(seed=1)
    o_one.step(0.0, external_drive=1.0)
    assert list(o_high._spike_rate_history) == list(o_one._spike_rate_history)

    o_neg = SelfRhythmOscillator(seed=1)
    o_neg.step(0.0, external_drive=-1.0)

    o_zero = SelfRhythmOscillator(seed=1)
    o_zero.step(0.0, external_drive=0.0)
    assert list(o_neg._spike_rate_history) == list(o_zero._spike_rate_history)

    o_nan = SelfRhythmOscillator(seed=1)
    o_nan.step(0.0, external_drive=math.nan)
    assert list(o_nan._spike_rate_history) == list(o_zero._spike_rate_history)


def test_amplitude_window_and_nonnegativity():
    o = SelfRhythmOscillator(seed=5)
    for i in range(MIN_PLV_WINDOW - 1):
        o.step(0.5)
        assert o.amplitude() == 0.0
    o.step(0.5)
    assert o.amplitude() >= 0.0
    assert math.isfinite(o.amplitude())


def test_serialize_round_trip_kind():
    o = SelfRhythmOscillator(seed=9)
    for _ in range(MIN_PLV_WINDOW + 4):
        o.step(0.6)
    state = o.serialize()
    assert state["kind"] == "self_rhythm"

    o2 = SelfRhythmOscillator(seed=9)
    o2.deserialize(state)
    assert list(o._spike_rate_history) == list(o2._spike_rate_history)
    assert o2.serialize()["kind"] == "self_rhythm"


def test_make_self_rhythm_oscillator_none_without_snntorch(monkeypatch):
    monkeypatch.setattr(
        "kaine.oscillator.module_oscillator.snntorch_available", lambda: False
    )
    assert make_self_rhythm_oscillator() is None


def test_no_external_drive_is_the_parent_path_even_above_one() -> None:
    # ModuleOscillator accepts drives above 1 unclamped; with no external drive
    # the self-rhythm must take exactly the parent's path, not a clamped sum.
    drives = [0.2, 1.7, 3.0, 0.0, 2.5] * 4
    a = ModuleOscillator(seed=5)
    b = SelfRhythmOscillator(seed=5)
    for d in drives:
        a.step(d)
        b.step(d)
    assert list(a._spike_rate_history) == list(b._spike_rate_history)
