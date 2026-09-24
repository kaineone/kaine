# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for oscillator continuity across Spot module restarts."""

from typing import Any

import pytest

from kaine.boot import build_registry, known_module_names, rewire_module
from kaine.bus.client import AsyncBus
from kaine.plugins import load_plugins
from tests.test_plugins_integration import (
    _bus,
    _close_module,
    _eps,
    _FakeDist,
    _FakeEP,
    _FreshNousOscillatorPlugin,
    _NousEnginePlugin,
    _spot,
)


@pytest.fixture
async def bus() -> AsyncBus:
    bus = _bus()
    yield bus
    await bus.close()


class _RecordingDefaultOscillator:
    """Stand-in default oscillator that records every step call."""

    def __init__(self) -> None:
        self.steps: list[float] = []
        self._frequency = 1.0
        self._phase = 0.0

    def step(self, dt: float) -> None:
        self.steps.append(dt)

    def phase(self) -> float:
        return self._phase

    def set_frequency(self, frequency: float) -> None:
        self._frequency = frequency

    def serialize(self) -> dict[str, Any]:
        return {
            "steps": list(self.steps),
            "frequency": self._frequency,
            "phase": self._phase,
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        self.steps = list(state.get("steps", []))
        self._frequency = state.get("frequency", 1.0)
        self._phase = state.get("phase", 0.0)


class _CountedDefaultOscFactory:
    """Factory that returns fresh recording oscillators and counts calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, **kwargs: Any) -> _RecordingDefaultOscillator:
        self.calls += 1
        return _RecordingDefaultOscillator()


@pytest.mark.asyncio
async def test_plugin_oscillator_not_re_requested(monkeypatch, bus):
    """A plugin-supplied oscillator is requested once at boot and never again,
    even after two heavy restarts of the module."""
    monkeypatch.setattr("kaine.oscillator.snntorch_available", lambda: False)

    engine_plugin = _NousEnginePlugin()
    osc_plugin = _FreshNousOscillatorPlugin()
    config = {
        "modules": {"nous": True},
        "oscillator": {"enabled": True},
        "plugins": {"enabled": ["nousengine", "nousosc"]},
    }
    loaded = load_plugins(
        config,
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("nousengine", lambda: engine_plugin, dist=_FakeDist("eng", "1")),
            _FakeEP("nousosc", lambda: osc_plugin, dist=_FakeDist("osc", "1")),
        ),
    )

    registry = build_registry(bus, config, plugins=loaded)
    original_nous = registry.get("nous")
    original_osc = original_nous.oscillator
    assert engine_plugin.calls == 1
    assert original_nous.engine.call_id == 1
    assert original_osc is not None and original_osc.call_id == 1
    assert osc_plugin.calls == 1

    spot = _spot(registry, config, bus)
    first = await spot._restart_module("nous")
    second = await spot._restart_module("nous")
    assert first.ok and first.path == "heavy"
    assert second.ok and second.path == "heavy"

    rebuilt_nous = registry.get("nous")
    assert engine_plugin.calls == 3
    assert rebuilt_nous.engine.call_id == 3
    assert osc_plugin.calls == 1
    assert rebuilt_nous.oscillator is original_osc
    assert rebuilt_nous.oscillator.call_id == 1

    await _close_module(rebuilt_nous)


@pytest.mark.asyncio
async def test_default_oscillator_continuity(monkeypatch, bus):
    """Heavy restarts preserve the default oscillator object and its step
    history; other modules keep their original oscillator as well."""
    pytest.importorskip("torch")

    factory = _CountedDefaultOscFactory()
    monkeypatch.setattr("kaine.oscillator.snntorch_available", lambda: True)
    monkeypatch.setattr("kaine.oscillator.make_oscillator", factory)

    engine_plugin = _NousEnginePlugin()
    config = {
        "modules": {"nous": True, "chronos": True},
        "oscillator": {"enabled": True},
        "plugins": {"enabled": ["nousengine"]},
    }
    loaded = load_plugins(
        config,
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("nousengine", lambda: engine_plugin, dist=_FakeDist("eng", "1")),
        ),
    )

    registry = build_registry(bus, config, plugins=loaded)
    original = {m.name: m.oscillator for m in registry.all_modules()}
    assert original["nous"] is not None
    assert original["chronos"] is not None
    assert factory.calls == 2

    for _ in range(3):
        original["nous"].step(0.5)

    spot = _spot(registry, config, bus)
    first = await spot._restart_module("nous")
    second = await spot._restart_module("nous")
    assert first.ok and first.path == "heavy"
    assert second.ok and second.path == "heavy"

    current = {m.name: m.oscillator for m in registry.all_modules()}
    assert current["nous"] is original["nous"]
    assert current["nous"].steps == [0.5, 0.5, 0.5]
    assert current["chronos"] is original["chronos"]
    assert factory.calls == 2

    await _close_module(registry.get("nous"))
    await _close_module(registry.get("chronos"))


@pytest.mark.asyncio
async def test_light_restart_keeps_oscillator(monkeypatch, bus):
    """A light restart leaves the module's oscillator object untouched and
    does not call the oscillator factory again."""
    pytest.importorskip("torch")

    factory = _CountedDefaultOscFactory()
    monkeypatch.setattr("kaine.oscillator.snntorch_available", lambda: True)
    monkeypatch.setattr("kaine.oscillator.make_oscillator", factory)

    engine_plugin = _NousEnginePlugin()
    config = {
        "modules": {"nous": True, "chronos": True},
        "oscillator": {"enabled": True},
        "plugins": {"enabled": ["nousengine"]},
    }
    loaded = load_plugins(
        config,
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("nousengine", lambda: engine_plugin, dist=_FakeDist("eng", "1")),
        ),
    )

    registry = build_registry(bus, config, plugins=loaded)
    original_chronos_osc = registry.get("chronos").oscillator
    assert factory.calls == 2

    spot = _spot(registry, config, bus)
    result = await spot._restart_module("chronos")
    assert result.ok and result.path == "light"
    assert registry.get("chronos").oscillator is original_chronos_osc
    assert factory.calls == 2

    await _close_module(registry.get("chronos"))
    await _close_module(registry.get("nous"))


@pytest.mark.asyncio
async def test_layer_disabled_no_oscillator_built(monkeypatch, bus):
    """With the oscillator layer disabled, modules have no oscillator and the
    default factory is never invoked, even through heavy restarts."""
    factory = _CountedDefaultOscFactory()
    monkeypatch.setattr("kaine.oscillator.snntorch_available", lambda: True)
    monkeypatch.setattr("kaine.oscillator.make_oscillator", factory)

    engine_plugin = _NousEnginePlugin()
    config = {
        "modules": {"nous": True},
        "oscillator": {"enabled": False},
        "plugins": {"enabled": ["nousengine"]},
    }
    loaded = load_plugins(
        config,
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("nousengine", lambda: engine_plugin, dist=_FakeDist("eng", "1")),
        ),
    )

    registry = build_registry(bus, config, plugins=loaded)
    assert registry.get("nous").oscillator is None
    assert factory.calls == 0

    spot = _spot(registry, config, bus)
    first = await spot._restart_module("nous")
    second = await spot._restart_module("nous")
    assert first.ok and first.path == "heavy"
    assert second.ok and second.path == "heavy"

    assert registry.get("nous").oscillator is None
    assert factory.calls == 0

    await _close_module(registry.get("nous"))


@pytest.mark.asyncio
async def test_rewire_module_no_oscillator_build(monkeypatch, bus):
    """rewire_module must not create or replace any oscillator objects."""
    pytest.importorskip("torch")

    boot_factory = _CountedDefaultOscFactory()
    monkeypatch.setattr("kaine.oscillator.snntorch_available", lambda: True)
    monkeypatch.setattr("kaine.oscillator.make_oscillator", boot_factory)

    engine_plugin = _NousEnginePlugin()
    config = {
        "modules": {"nous": True, "chronos": True},
        "oscillator": {"enabled": True},
        "plugins": {"enabled": ["nousengine"]},
    }
    loaded = load_plugins(
        config,
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("nousengine", lambda: engine_plugin, dist=_FakeDist("eng", "1")),
        ),
    )

    registry = build_registry(bus, config, plugins=loaded)
    original = {m.name: m.oscillator for m in registry.all_modules()}
    assert boot_factory.calls == 2

    rewire_factory = _CountedDefaultOscFactory()
    monkeypatch.setattr("kaine.oscillator.make_oscillator", rewire_factory)

    rewire_module(registry, "nous", config)

    assert rewire_factory.calls == 0
    for m in registry.all_modules():
        assert m.oscillator is original[m.name]

    await _close_module(registry.get("nous"))
    await _close_module(registry.get("chronos"))
