# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Boot stock KAINE's planning module through kaine's own plugin loader.

This file validates that the CL1 plugin wraps KAINE's engine through the
``planning.engine_wrapper`` seam defined by the OpenSpec nous-on-wetware contract.
"""

import os

import pytest

pytest.importorskip("kaine", reason="kaine boot tests require kaine package")
pytest.importorskip("fakeredis", reason="kaine boot tests require fakeredis")
pytest.importorskip("pymdp", reason="KAINE's Planning engine needs pymdp")

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import logging  # noqa: E402

import cl.sim as clsim  # noqa: E402
import fakeredis.aioredis  # noqa: E402
from kaine_cl1.backends.planning import WetwarePolicyEngine  # noqa: E402

from kaine.boot import build_registry, known_module_names  # noqa: E402
from kaine.bus.client import AsyncBus  # noqa: E402
from kaine.bus.config import BusConfig  # noqa: E402
from kaine.cycle.types import WorkspaceSnapshot  # noqa: E402
from kaine.plugins import PluginError, load_plugins  # noqa: E402


def _config(*, territory=10, mode=None):
    cl1 = {
        "substrate": {"target": "simulator", "accelerated_time": True, "territories": {"planning": territory}},
        "backends": {"planning": "cl1"},
    }
    if mode is not None:
        cl1["planning"] = {"mode": mode}
    return {
        "modules": {"planning": True},
        "planning": {"efe_timeout_ms": 60000.0},
        "plugins": {"enabled": ["cl1"], "cl1": cl1},
    }


def _bus():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _load(cfg):
    return load_plugins(cfg, known_modules=known_module_names())


def _close_cl1(plugins):
    for info in getattr(plugins, "_plugins", {}).values():
        obj = info.get("plugin")
        if obj is not None and hasattr(obj, "close"):
            obj.close()


@pytest.fixture
def reference_culture():
    clsim.set_simulator_data_source(
        "kaine_cl1.substrate.sources:make_reference_culture",
        config={
            "seed": 7,
            "baseline_hz": 2.0,
            "evoked_spikes": 16,
            "response_ms": 20.0,
        },
    )
    try:
        yield
    finally:
        clsim.clear_simulator_data_source()


def test_manifest_declares_the_engine_wrapper_seam():
    plugins = _load(_config())
    try:
        assert plugins.manifest_entry()["cl1"]["seams"] == ["planning.engine_wrapper"]
    finally:
        _close_cl1(plugins)


async def test_booted_planning_wraps_kaines_engine(reference_culture):
    bus = _bus()
    cfg = _config()
    plugins = _load(cfg)

    try:
        reg = build_registry(bus, cfg, plugins=plugins)
        planning = reg.get("planning")

        assert isinstance(planning.engine, WetwarePolicyEngine)
        assert len(planning.engine.actions) == 4
        assert type(planning.engine._inner).__name__ == "PymdpEngine"

        result = planning.engine.step(
            WorkspaceSnapshot(tick_index=1, selected_events=[], inhibited=False)
        )
        assert not result.timed_out and not result.error
        assert result.action == planning.engine.actions[result.action_index]
        assert planning.engine.proposal_count == 1

        assert planning.engine.close == planning.engine._inner.close
    finally:
        await bus.close()
        _close_cl1(plugins)


async def test_drive_mode_warns_at_boot(caplog):
    with caplog.at_level(logging.WARNING, logger="kaine_cl1.plugin"):
        plugins = _load(_config(mode="drive"))
        try:
            assert any("DRIVE mode" in r.getMessage() for r in caplog.records)
        finally:
            _close_cl1(plugins)


async def test_too_small_territory_fails_the_boot_naming_the_plugin():
    bus = _bus()
    cfg = _config(territory=4)
    plugins = _load(cfg)

    try:
        with pytest.raises(PluginError) as exc_info:
            build_registry(bus, cfg, plugins=plugins)

        message = str(exc_info.value)
        assert "cl1" in message
        assert "at least 10" in message
    finally:
        await bus.close()
        _close_cl1(plugins)


async def test_rebuild_reuses_the_territory(reference_culture):
    bus = _bus()
    cfg = _config()
    plugins = _load(cfg)

    try:
        reg1 = build_registry(bus, cfg, plugins=plugins)
        planning1 = reg1.get("planning")
        assert isinstance(planning1.engine, WetwarePolicyEngine)

        reg2 = build_registry(bus, cfg, plugins=plugins)
        planning2 = reg2.get("planning")
        assert isinstance(planning2.engine, WetwarePolicyEngine)
        assert planning1.engine is not planning2.engine
    finally:
        await bus.close()
        _close_cl1(plugins)
