# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""BaseModule oscillator hook (oscillatory-layer).

Covers phase() neutral fallback, attach/clear, set_frequency delegation, and
the publish-drives-oscillator path — all with FakeOscillator (no snnTorch).
"""
from __future__ import annotations

import asyncio

import pytest

from kaine.modules.base import BaseModule
from kaine.oscillator import NEUTRAL_PHASE, FakeOscillator


class _FakeBus:
    def __init__(self) -> None:
        self.published: list = []

    async def current_workspace_id(self) -> str:
        return "0"

    async def publish(self, event) -> str:
        self.published.append(event)
        return "1-0"


class _Mod(BaseModule):
    name = "osc_test"

    def __init__(self) -> None:
        super().__init__(_FakeBus())  # type: ignore[arg-type]


def test_phase_neutral_without_oscillator():
    assert _Mod().phase() == NEUTRAL_PHASE


def test_attach_and_phase_reports_oscillator():
    mod = _Mod()
    osc = FakeOscillator()
    mod.attach_oscillator(osc)
    osc.step(0.5)
    assert mod.oscillator is osc
    assert mod.phase() == osc.phase()


def test_attach_none_clears():
    mod = _Mod()
    mod.attach_oscillator(FakeOscillator())
    mod.attach_oscillator(None)
    assert mod.oscillator is None
    assert mod.phase() == NEUTRAL_PHASE


def test_set_frequency_noop_without_oscillator():
    # Must not raise — Hypnos invokes this unconditionally.
    _Mod().set_frequency(0.5)


def test_set_frequency_delegates_to_oscillator():
    received: list[float] = []

    class _TrackOsc(FakeOscillator):
        def set_frequency(self, scale: float) -> None:
            received.append(scale)

    mod = _Mod()
    mod.attach_oscillator(_TrackOsc())
    mod.set_frequency(0.25)
    assert received == [0.25]


def test_publish_drives_oscillator():
    stepped: list[float] = []

    class _TrackOsc(FakeOscillator):
        def step(self, drive: float) -> None:
            stepped.append(drive)
            super().step(drive)

    mod = _Mod()
    mod.attach_oscillator(_TrackOsc())
    asyncio.run(mod.publish("osc_test.out", {"x": 1}, salience=0.7))
    assert stepped == [0.7]
