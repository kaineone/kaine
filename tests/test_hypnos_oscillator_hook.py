# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the Phase-1 oscillator frequency-reduction hook (task 7.3).

Verifies that:
- ``BaseModule.set_frequency(scale)`` is a true no-op that raises no exception.
- Invoking ``set_frequency`` across active modules in light_consolidation never
  errors when the oscillatory-layer is absent (all modules use the BaseModule
  default no-op).
- The hook is called with the correct scale value.
- Subclasses can override ``set_frequency`` to receive real calls (forward
  compatibility check for when oscillatory-layer ships).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.modules.base import BaseModule
from kaine.modules.hypnos.phases import light_consolidation


# ---------------------------------------------------------------------------
# Minimal concrete BaseModule for testing (no bus needed for hook tests)
# ---------------------------------------------------------------------------

class _FakeBus:
    """Minimal bus stand-in (set_frequency tests don't touch the bus)."""

    async def current_workspace_id(self) -> str:
        return "0"

    async def subscribe_workspace(self, *, last_id: str):
        return
        yield  # make it a generator


class _ConcreteModule(BaseModule):
    """Smallest valid BaseModule subclass for testing."""
    name = "test_module"

    def __init__(self) -> None:
        # BaseModule.__init__ is synchronous and only needs a bus-shaped
        # object, so the fake bus satisfies it directly — no need to bypass
        # the real initialization (which also sets up the oscillator slot
        # and heartbeat that set_frequency/phase() rely on via getattr).
        super().__init__(_FakeBus())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test: set_frequency is a true no-op on BaseModule
# ---------------------------------------------------------------------------

def test_set_frequency_noop_on_base_module():
    """set_frequency(scale) must not raise on any valid or edge-case input."""
    mod = _ConcreteModule()
    # Normal use: scale < 1 (frequency reduction during sleep)
    mod.set_frequency(0.5)
    # Edge cases
    mod.set_frequency(0.0)
    mod.set_frequency(1.0)
    mod.set_frequency(2.0)
    mod.set_frequency(-0.1)  # arbitrary; no-op accepts anything
    # No assertion needed — reaching here means no exception raised


def test_set_frequency_returns_none():
    """set_frequency must return None (no-op)."""
    mod = _ConcreteModule()
    result = mod.set_frequency(0.5)
    assert result is None


# ---------------------------------------------------------------------------
# Test: set_frequency called across all active modules in phase 1
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_light_consolidation_invokes_set_frequency_noop():
    """light_consolidation calls set_frequency on each module; no error raised."""
    modules = [_ConcreteModule() for _ in range(4)]
    # All are no-ops — must not raise
    r = await light_consolidation(None, active_modules=modules, frequency_scale=0.5)
    assert r.success is True
    assert r.metadata["modules_frequency_called"] == 4


@pytest.mark.asyncio
async def test_light_consolidation_noop_with_no_modules():
    """Empty active_modules list: light_consolidation succeeds, zero hook calls."""
    r = await light_consolidation(None, active_modules=[], frequency_scale=0.5)
    assert r.success is True
    assert r.metadata["modules_frequency_called"] == 0


@pytest.mark.asyncio
async def test_light_consolidation_correct_scale_passed():
    """set_frequency receives exactly the configured frequency_scale."""
    received: list[float] = []

    class _TrackingModule(_ConcreteModule):
        def set_frequency(self, scale: float) -> None:
            received.append(scale)

    modules = [_TrackingModule()]
    await light_consolidation(None, active_modules=modules, frequency_scale=0.25)
    assert received == [0.25]


# ---------------------------------------------------------------------------
# Test: subclass override (forward-compat for oscillatory-layer)
# ---------------------------------------------------------------------------

def test_subclass_can_override_set_frequency():
    """Subclasses can provide a real body; the no-op is easily replaced."""
    class _OscillatoryModule(_ConcreteModule):
        def __init__(self):
            super().__init__()
            self.last_scale: float | None = None

        def set_frequency(self, scale: float) -> None:
            # Real oscillatory-layer body would reconfigure LIF oscillator here.
            self.last_scale = scale

    mod = _OscillatoryModule()
    mod.set_frequency(0.3)
    assert mod.last_scale == 0.3


@pytest.mark.asyncio
async def test_oscillatory_subclass_called_by_light_consolidation():
    """When oscillatory-layer module is in active_modules, its set_frequency fires."""

    class _OscillatoryModule(_ConcreteModule):
        name = "osc_module"

        def __init__(self):
            super().__init__()
            self.scale_calls: list[float] = []

        def set_frequency(self, scale: float) -> None:
            self.scale_calls.append(scale)

    osc = _OscillatoryModule()
    plain = _ConcreteModule()
    await light_consolidation(None, active_modules=[osc, plain], frequency_scale=0.4)
    # Oscillatory module received the call; plain module silently accepted it
    assert osc.scale_calls == [0.4]


# ---------------------------------------------------------------------------
# Test: exception in set_frequency is caught; pipeline continues
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_frequency_exception_in_one_module_does_not_abort():
    """If one module's set_frequency raises, light_consolidation still succeeds."""

    class _BoomModule(_ConcreteModule):
        name = "boom"

        def set_frequency(self, scale: float) -> None:
            raise RuntimeError("oscillator not ready")

    class _GoodModule(_ConcreteModule):
        name = "good"
        calls: int = 0

        def set_frequency(self, scale: float) -> None:
            _GoodModule.calls += 1

    boom = _BoomModule()
    good = _GoodModule()
    _GoodModule.calls = 0

    r = await light_consolidation(None, active_modules=[boom, good], frequency_scale=0.5)
    # Boom raised — counted as 0 successful calls for that module, but
    # the phase itself succeeds and the good module was still called.
    assert r.success is True
    assert _GoodModule.calls == 1
