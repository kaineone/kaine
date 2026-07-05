# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the per-module oscillatory-binding oscillator (oscillatory-layer).

Covers FakeOscillator determinism + no-op set_frequency, the lazy/graceful
snnTorch fallback, and — when snnTorch is installed — the real LIF
ModuleOscillator's phase output, set_frequency drive scaling, and serialize
roundtrip. The suite stays green WITHOUT snnTorch: real-oscillator tests skip
when it is absent, and a monkeypatched-absent test proves the neutral fallback.
"""
from __future__ import annotations

import math

import pytest

from kaine.oscillator import (
    NEUTRAL_PHASE,
    FakeOscillator,
    make_oscillator,
    neutral_phase,
    snntorch_available,
)
from kaine.oscillator import module_oscillator as mo

_HAS_SNN = snntorch_available()
requires_snn = pytest.mark.skipif(not _HAS_SNN, reason="snnTorch/scipy not installed")


# --------------------------------------------------------------------------
# FakeOscillator — deterministic, dependency-free
# --------------------------------------------------------------------------

def test_fake_oscillator_deterministic_phase():
    a = FakeOscillator()
    b = FakeOscillator()
    for _ in range(10):
        a.step(0.9)
        b.step(0.1)  # different drive must not change the deterministic phase
    assert a.phase() == b.phase()


def test_fake_oscillator_advances_phase():
    f = FakeOscillator()
    start = f.phase()
    f.step(0.5)
    assert f.phase() != start
    assert 0.0 <= f.phase() < 2.0 * math.pi


def test_fake_oscillator_set_frequency_is_noop():
    f = FakeOscillator()
    for _ in range(4):
        f.step(0.5)
    before = f.phase()
    f.set_frequency(0.1)  # must not raise, must not change phase
    f.set_frequency(0.0)
    assert f.phase() == before


def test_fake_oscillator_serialize_roundtrip():
    f = FakeOscillator()
    for _ in range(7):
        f.step(0.5)
    state = f.serialize()
    g = FakeOscillator()
    g.deserialize(state)
    assert g.phase() == f.phase()


# --------------------------------------------------------------------------
# Real LIF ModuleOscillator (snnTorch)
# --------------------------------------------------------------------------

@requires_snn
def test_make_oscillator_builds_when_available():
    osc = make_oscillator(seed=1)
    assert osc is not None


@requires_snn
def test_real_oscillator_returns_finite_phase_after_activity():
    osc = make_oscillator(seed=3)
    for _ in range(40):
        osc.step(0.8)
    ph = osc.phase()
    assert math.isfinite(ph)


@requires_snn
def test_real_oscillator_neutral_before_enough_samples():
    osc = make_oscillator(seed=3, plv_window=10)
    osc.step(0.8)  # only one sample
    assert osc.phase() == NEUTRAL_PHASE


@requires_snn
def test_set_frequency_scales_drive():
    osc = make_oscillator(seed=5)
    assert osc.drive_scale == 1.0
    osc.set_frequency(0.5)
    assert osc.drive_scale == 0.5
    osc.set_frequency(-1.0)  # clamped to 0.0
    assert osc.drive_scale == 0.0


@requires_snn
def test_real_oscillator_serialize_roundtrip():
    osc = make_oscillator(seed=7)
    for _ in range(40):
        osc.step(0.7)
    osc.set_frequency(0.5)
    state = osc.serialize()
    other = make_oscillator(seed=99)
    other.deserialize(state)
    assert other.drive_scale == osc.drive_scale
    assert abs(other.phase() - osc.phase()) < 1e-9


@requires_snn
def test_population_and_window_minimums_enforced():
    with pytest.raises(ValueError):
        mo.ModuleOscillator(population_size=8)
    with pytest.raises(ValueError):
        mo.ModuleOscillator(plv_window=5)


# --------------------------------------------------------------------------
# Graceful fallback when snnTorch is absent
# --------------------------------------------------------------------------

def test_make_oscillator_returns_none_when_snntorch_absent(monkeypatch):
    monkeypatch.setattr(mo, "snntorch_available", lambda: False)
    assert make_oscillator() is None


def test_neutral_phase_constant():
    assert neutral_phase() == NEUTRAL_PHASE
