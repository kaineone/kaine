# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Integration tests for KAINE plugin seams through real boot paths."""
import asyncio
import contextlib
import logging
from typing import Any

import pytest

from kaine.boot import build_registry, known_module_names
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.__main__ import _make_rebuild_module
from kaine.cycle.types import WorkspaceSnapshot
from kaine.experiment.run_context import mint_run_context
from kaine.modules.base import BaseModule
from kaine.plugins import PluginError, load_plugins


class _FakeDist:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version


class _FakeEP:
    def __init__(self, name: str, factory, dist=None):
        self.name = name
        self._factory = factory
        self.dist = dist

    def load(self):
        return self._factory


def _eps(*eps):
    return lambda group="kaine.plugins": list(eps)


class _FakeNetwork:
    units = 8

    def __init__(self):
        self.calls = 0

    def tick(self, feature_vec):
        self.calls += 1
        return [0.0] * self.units


class _ChronosNetworkPlugin:
    def __init__(self, network_factory):
        self._network_factory = network_factory
        self.calls = 0

    def seams(self, config):
        return frozenset({"chronos.network"})

    def injections(self, module, config):
        if module == "chronos":
            self.calls += 1
            return {"network": self._network_factory()}
        return {}


class _OscillatorPlugin:
    def __init__(self, module: str, osc: Any | None):
        self._module = module
        self._osc = osc

    def seams(self, config):
        return frozenset({f"oscillator.{self._module}"})

    def make_oscillator(self, module, config, defaults):
        if module != self._module:
            return None
        return self._osc


class _RecordingOscillator:
    pass


def _bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


@pytest.fixture
async def bus() -> AsyncBus:
    bus = _bus()
    yield bus
    await bus.close()


def _empty_snapshot(tick: int = 0) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=tick, selected_events=[], inhibited=False)


async def _close_module(module: Any) -> None:
    for attr in ("close", "shutdown"):
        fn = getattr(module, attr, None)
        if callable(fn):
            # Best-effort teardown of a test module: a close/shutdown error must
            # not mask the assertion that already ran.
            with contextlib.suppress(Exception):
                if asyncio.iscoroutinefunction(fn):
                    await fn()
                else:
                    fn()
            return
    stopped = getattr(module, "_stopped", None)
    if stopped is not None:
        stopped.set()
    for task in list(getattr(module, "_tasks", [])):
        if not task.done():
            task.cancel()
            # Wait for the cancelled task to finish; its CancelledError is
            # returned rather than raised.
            await asyncio.gather(task, return_exceptions=True)


class _NoneInjectionPlugin:
    def __init__(self, module: str, key: str):
        self._module = module
        self._key = key

    def seams(self, config):
        return frozenset({f"{self._module}.{self._key}"})

    def injections(self, module, config):
        if module == self._module:
            return {self._key: None}
        return {}


class _BoomPymdpEngine:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("PymdpEngine should not be instantiated")


class _EngineResult:
    def __init__(self):
        self.error = False
        self.timed_out = False
        self.posterior = [[0.5, 0.5]]
        self.policy = []
        self.actions = []
        self.efe = 0.0


class _FakeNousEngine:
    def __init__(self, call_id: int):
        self.call_id = call_id
        self.actions = ["no_op"]

    def step(self, snapshot):
        return _EngineResult()

    def close(self):
        pass


class _NousEnginePlugin:
    def __init__(self):
        self.calls = 0

    def seams(self, config):
        return frozenset({"nous.engine"})

    def injections(self, module, config):
        if module == "nous":
            self.calls += 1
            return {"engine": _FakeNousEngine(self.calls)}
        return {}


class _CallCountingOscillator:
    def __init__(self, call_id: int):
        self.call_id = call_id


class _FreshNousOscillatorPlugin:
    def __init__(self):
        self.calls = 0

    def seams(self, config):
        return frozenset({"oscillator.nous"})

    def make_oscillator(self, module, config, defaults):
        if module != "nous":
            return None
        self.calls += 1
        return _CallCountingOscillator(self.calls)


class _DummyForkManager:
    def restore(self, last_good, registry):
        pass


# ---------------------------------------------------------------------------
# 4.4  build_registry with a plugin filling chronos.network
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_registry_plugin_fills_chronos_network(caplog, bus):
    plugin_net = _FakeNetwork()
    plugin = _ChronosNetworkPlugin(lambda: plugin_net)
    lp = load_plugins(
        {"plugins": {"enabled": ["chronosnet"]}},
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("chronosnet", lambda: plugin, dist=_FakeDist("pkg", "1.2.3"))
        ),
    )
    config = {"modules": {"chronos": True}}
    with caplog.at_level(logging.WARNING, logger="kaine.plugins"):
        registry = build_registry(bus, config, plugins=lp)
    chronos = registry.get("chronos")
    assert chronos._network is plugin_net
    assert any(
        "plugin chronosnet fills chronos.network" in rec.message
        for rec in caplog.records
    )

    default_registry = build_registry(bus, config, plugins=None)
    default_chronos = default_registry.get("chronos")
    assert not default_chronos._network_injected


# ---------------------------------------------------------------------------
# 4.5 + 4.10  Spot restarts re-request plugin injections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spot_restart_re_requests_fresh_plugin_network(bus):
    pytest.importorskip("torch")
    plugin = _ChronosNetworkPlugin(_FakeNetwork)
    lp = load_plugins(
        {"plugins": {"enabled": ["chronosnet"]}},
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("chronosnet", lambda: plugin, dist=_FakeDist("pkg", "1.2.3"))
        ),
    )
    config = {
        "modules": {"chronos": True},
        "chronos": {"forward_prediction": True},
    }
    registry = build_registry(bus, config, plugins=lp)
    rebuild = _make_rebuild_module(bus, config, registry, None)

    instances = []
    for _ in range(2):
        chronos = rebuild("chronos")
        await chronos.initialize()
        await chronos.on_workspace(_empty_snapshot())
        instances.append(chronos)

    # One request at boot plus one per restart, each a fresh object.
    boot_network = registry.get("chronos")._network
    networks = [boot_network, instances[0]._network, instances[1]._network]
    assert len({id(n) for n in networks}) == 3
    assert plugin.calls == 3
    for chronos in instances:
        await _close_module(chronos)


# ---------------------------------------------------------------------------
# 4.6  Oscillator seams
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_oscillator_attached_without_snntorch(monkeypatch, bus):
    monkeypatch.setattr("kaine.oscillator.snntorch_available", lambda: False)
    osc = _RecordingOscillator()
    plugin = _OscillatorPlugin("chronos", osc)
    lp = load_plugins(
        {"plugins": {"enabled": ["oscplugin"]}, "oscillator": {"enabled": True}},
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("oscplugin", lambda: plugin, dist=_FakeDist("pkg", "2.0"))
        ),
    )

    attached: list[tuple[str, Any]] = []
    original = BaseModule.attach_oscillator

    def _recording_attach(self, osc):
        attached.append((self.name, osc))
        return original(self, osc)

    monkeypatch.setattr(BaseModule, "attach_oscillator", _recording_attach)

    config = {
        "modules": {"chronos": True, "soma": True},
        "oscillator": {"enabled": True},
    }
    build_registry(bus, config, plugins=lp)

    assert ("chronos", osc) in attached
    assert not any(name == "soma" for name, _ in attached)


@pytest.mark.asyncio
async def test_plugin_oscillator_none_raises_plugin_error(bus):
    plugin = _OscillatorPlugin("chronos", None)
    lp = load_plugins(
        {"plugins": {"enabled": ["badosc"]}, "oscillator": {"enabled": True}},
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("badosc", lambda: plugin, dist=_FakeDist("pkg", "1.0"))
        ),
    )
    config = {
        "modules": {"chronos": True},
        "oscillator": {"enabled": True},
    }
    with pytest.raises(PluginError, match="returned None"):
        build_registry(bus, config, plugins=lp)


def test_two_plugins_claim_same_oscillator_seam():
    p1 = _OscillatorPlugin("chronos", _RecordingOscillator())
    p2 = _OscillatorPlugin("chronos", _RecordingOscillator())
    with pytest.raises(PluginError, match="both declare seam oscillator.chronos"):
        load_plugins(
            {"plugins": {"enabled": ["osc1", "osc2"]}, "oscillator": {"enabled": True}},
            known_modules=known_module_names(),
            entry_points=_eps(
                _FakeEP("osc1", lambda: p1, dist=_FakeDist("pkg1", "1")),
                _FakeEP("osc2", lambda: p2, dist=_FakeDist("pkg2", "1")),
            ),
        )


# ---------------------------------------------------------------------------
# 4.7  Manifest recording
# ---------------------------------------------------------------------------


def test_manifest_records_plugin_metadata():
    plugin = _ChronosNetworkPlugin(_FakeNetwork)
    lp = load_plugins(
        {"plugins": {"enabled": ["chronosnet"]}},
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("chronosnet", lambda: plugin, dist=_FakeDist("my-dist", "1.2.3"))
        ),
    )
    rc = mint_run_context(
        seed=0,
        started_at="2026-01-01T00:00:00+00:00",
        config={"modules": {}},
        model_ids={},
        version="test",
        plugins=lp.manifest_entry(),
    )
    assert rc.to_dict()["plugins"] == {
        "chronosnet": {
            "distribution": "my-dist",
            "version": "1.2.3",
            "seams": ["chronos.network"],
        }
    }

    empty = load_plugins({}, known_modules=known_module_names(), entry_points=_eps())
    rc_empty = mint_run_context(
        seed=0,
        started_at="2026-01-01T00:00:00+00:00",
        config={},
        model_ids={},
        version="test",
        plugins=empty.manifest_entry(),
    )
    assert rc_empty.to_dict()["plugins"] == {}


# ---------------------------------------------------------------------------
# cycle main propagates PluginError
# ---------------------------------------------------------------------------


def test_cycle_main_catches_plugin_error(monkeypatch, capsys):
    monkeypatch.setenv("KAINE_CYCLE_OPERATOR_PRESENT", "1")
    monkeypatch.setattr(
        "kaine.cycle.__main__._load_kaine_config",
        lambda profile=None: {"modules": {}},
    )

    async def _raise_plugin_error(supervision_mode, gate_checks):
        raise PluginError("plugin x could not supply seam")

    monkeypatch.setattr("kaine.cycle.__main__._boot_and_run", _raise_plugin_error)

    from kaine.cycle.__main__ import main

    rc = main([])
    captured = capsys.readouterr()
    assert rc == 1
    assert "kaine.cycle: plugin error:" in captured.err


@pytest.mark.parametrize(
    "module,key",
    [
        ("chronos", "network"),
        ("soma", "forward_model"),
        ("nous", "engine"),
    ],
)
async def test_none_injection_fails_closed(module, key, bus):
    """A declared seam returned as None fails closed instead of letting the
    module build its default model while the manifest records a substitution."""
    plugin = _NoneInjectionPlugin(module, key)
    loaded = load_plugins(
        {"plugins": {"enabled": ["noneplugin"]}},
        known_modules=known_module_names(),
        entry_points=_eps(_FakeEP("noneplugin", lambda: plugin, dist=_FakeDist("x", "1"))),
    )

    with pytest.raises(PluginError) as exc:
        loaded.injections_for(module)
    msg = str(exc.value)
    assert "None" in msg
    assert f"{module}.{key}" in msg

    with pytest.raises(PluginError):
        build_registry(bus, {"modules": {module: True}}, plugins=loaded)


@pytest.mark.asyncio
async def test_nous_falsy_injected_engine_held_not_default(monkeypatch, bus):
    """An injected engine that is falsy is still the engine Nous uses."""
    monkeypatch.setattr("kaine.modules.nous.engine.PymdpEngine", _BoomPymdpEngine)

    class FalsyEngine:
        def __len__(self):
            return 0

        def step(self, snapshot):
            return _EngineResult()

        @property
        def actions(self):
            return []

    engine = FalsyEngine()
    assert not engine

    from kaine.boot import make_nous

    nous = make_nous(bus, {}, injections={"engine": engine})
    assert nous.engine is engine


def _spot(registry, config, bus):
    from kaine.cycle.spot import IncidentLogConfig, Spot, SpotConfig

    return Spot(
        registry=registry,
        fork_manager=_DummyForkManager(),
        kaine_config=config,
        config=SpotConfig(incident_log=IncidentLogConfig(enabled=False)),
        rebuild_module=_make_rebuild_module(bus, config, registry, None),
        bus=bus,
    )


@pytest.mark.asyncio
async def test_spot_nous_heavy_restart_refreshes_engine_keeps_oscillator(monkeypatch, bus):
    """Two real Spot heavy restarts of Nous each request a fresh engine from the
    plugin (tasks 4.5 / 4.10), while the plugin oscillator is requested once at
    boot and carried over unchanged (oscillator-continuity-on-restart)."""
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
    nous = registry.get("nous")
    assert engine_plugin.calls == 1
    assert nous.engine.call_id == 1
    assert nous._oscillator is not None and nous._oscillator.call_id == 1
    boot_oscillator = nous._oscillator

    spot = _spot(registry, config, bus)
    first = await spot._restart_module("nous")
    second = await spot._restart_module("nous")
    assert first.ok and first.path == "heavy"
    assert second.ok and second.path == "heavy"

    nous = registry.get("nous")
    assert engine_plugin.calls == 3
    assert nous.engine.call_id == 3
    assert osc_plugin.calls == 1
    assert nous._oscillator is boot_oscillator

    await _close_module(nous)


@pytest.mark.asyncio
async def test_spot_chronos_light_restart_keeps_same_network(bus):
    """Chronos restarts in place: it keeps its injected network and the plugin
    is not asked again."""
    network_plugin = _ChronosNetworkPlugin(_FakeNetwork)
    config = {"modules": {"chronos": True}, "plugins": {"enabled": ["chronosnet"]}}
    loaded = load_plugins(
        config,
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP("chronosnet", lambda: network_plugin, dist=_FakeDist("c", "1"))
        ),
    )

    registry = build_registry(bus, config, plugins=loaded)
    before = registry.get("chronos")._network
    assert network_plugin.calls == 1

    spot = _spot(registry, config, bus)
    result = await spot._restart_module("chronos")
    assert result.ok and result.path == "light"
    assert network_plugin.calls == 1
    assert registry.get("chronos")._network is before

    await _close_module(registry.get("chronos"))
