# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""tests for the nous.engine_wrapper plugin seam (OpenSpec plugin-engine-wrapper)."""

import asyncio
import inspect

import pytest

from kaine.boot import ConfigurationError, make_nous
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.nous import FakeEngine
from kaine.plugins import PluginError, load_plugins


def _bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _engine_of(nous):
    return getattr(nous, "engine", getattr(nous, "_engine", None))


def _close_if_present(obj):
    close = getattr(obj, "close", None)
    if not callable(close):
        return
    if inspect.iscoroutinefunction(close):
        asyncio.run(close())
    else:
        close()


class FakeDist:
    def __init__(self, name="fake-dist", version="0.0.0"):
        self.name = name
        self.version = version


class FakeEP:
    def __init__(self, name, factory, dist=None):
        self.name = name
        self._factory = factory
        self.dist = dist

    def load(self):
        return self._factory


def _eps(*eps):
    return lambda group="kaine.plugins": list(eps)


class _Plugin:
    def __init__(self, seams, injections):
        self._seams = frozenset(seams)
        self._injections = dict(injections)

    def seams(self, config):
        return self._seams

    def injections(self, module, config):
        return self._injections.get(module, {})


def test_wrapper_receives_the_default_engine_built_from_config():
    pytest.importorskip("pymdp")
    from kaine.modules.nous.engine import PymdpEngine

    seen = []

    def wrap(eng):
        seen.append(eng)
        return FakeEngine()

    bus = _bus()
    try:
        nous = make_nous(bus, {"planning_horizon": 2}, injections={"engine_wrapper": wrap})
        assert len(seen) == 1
        assert isinstance(seen[0], PymdpEngine)
        assert isinstance(_engine_of(nous), FakeEngine)
    finally:
        for eng in seen:
            _close_if_present(eng)
        asyncio.run(bus.close())


def test_wrapper_returning_a_non_engine_fails_naming_the_plugin():
    pytest.importorskip("pymdp")
    plugin = _Plugin(
        {"nous.engine_wrapper"},
        {"nous": {"engine_wrapper": lambda eng: object()}},
    )
    ep = FakeEP("wrapper_plugin", lambda: plugin, FakeDist())
    lp = load_plugins(
        {"plugins": {"enabled": ["wrapper_plugin"]}},
        known_modules=["nous"],
        entry_points=_eps(ep),
    )
    inj = lp.injections_for("nous")
    bus = _bus()
    try:
        with pytest.raises(ConfigurationError, match="wrapper_plugin"):
            make_nous(bus, {}, injections=inj)
    finally:
        asyncio.run(bus.close())


def test_wrapper_exception_becomes_plugin_error():
    pytest.importorskip("pymdp")

    def bad_wrap(eng):
        raise RuntimeError("nope")

    plugin = _Plugin(
        {"nous.engine_wrapper"},
        {"nous": {"engine_wrapper": bad_wrap}},
    )
    ep = FakeEP("boom_plugin", lambda: plugin, FakeDist())
    lp = load_plugins(
        {"plugins": {"enabled": ["boom_plugin"]}},
        known_modules=["nous"],
        entry_points=_eps(ep),
    )
    inj = lp.injections_for("nous")
    bus = _bus()
    try:
        with pytest.raises(PluginError, match="boom_plugin"):
            make_nous(bus, {}, injections=inj)
    finally:
        asyncio.run(bus.close())


def test_non_callable_wrapper_rejected_at_injection():
    plugin = _Plugin(
        {"nous.engine_wrapper"},
        {"nous": {"engine_wrapper": 42}},
    )
    ep = FakeEP("bad_plugin", lambda: plugin, FakeDist())
    lp = load_plugins(
        {"plugins": {"enabled": ["bad_plugin"]}},
        known_modules=["nous"],
        entry_points=_eps(ep),
    )
    with pytest.raises(PluginError, match="non-callable"):
        lp.injections_for("nous")


def test_engine_and_wrapper_together_rejected_at_load():
    replacer = _Plugin({"nous.engine"}, {})
    wrapper = _Plugin({"nous.engine_wrapper"}, {})
    eps = _eps(
        FakeEP("replacer", lambda: replacer, FakeDist()),
        FakeEP("wrapper", lambda: wrapper, FakeDist()),
    )
    with pytest.raises(PluginError) as exc_info:
        load_plugins(
            {"plugins": {"enabled": ["replacer", "wrapper"]}},
            known_modules=["nous"],
            entry_points=eps,
        )
    msg = str(exc_info.value)
    assert "replacer" in msg
    assert "wrapper" in msg


def test_make_nous_rejects_both_injections():
    bus = _bus()
    try:
        with pytest.raises(ConfigurationError, match="both"):
            make_nous(
                bus,
                {},
                injections={
                    "engine": FakeEngine(),
                    "engine_wrapper": lambda e: e,
                },
            )
    finally:
        asyncio.run(bus.close())


def test_replacement_path_unchanged():
    bus = _bus()
    fe = FakeEngine()
    try:
        nous = make_nous(bus, {}, injections={"engine": fe})
        assert _engine_of(nous) is fe
    finally:
        asyncio.run(bus.close())


def test_wrapper_called_again_on_rebuild():
    pytest.importorskip("pymdp")
    count = []

    def wrap(eng):
        count.append(eng)
        return FakeEngine()

    injections = {"engine_wrapper": wrap}
    bus = _bus()
    try:
        first = make_nous(bus, {}, injections=injections)
        second = make_nous(bus, {}, injections=injections)
        assert len(count) == 2
        assert count[0] is not count[1]
        assert isinstance(_engine_of(first), FakeEngine)
        assert isinstance(_engine_of(second), FakeEngine)
    finally:
        for eng in count:
            _close_if_present(eng)
        asyncio.run(bus.close())

