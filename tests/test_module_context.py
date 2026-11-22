# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import kaine.persistence.jsonl_sink as jsonl_sink_mod
import kaine.privacy_filter as privacy_mod
import kaine.state_io as state_io_mod
import kaine.storage as storage_mod
from kaine.boot.registry import build_registry
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.modules.context_services import ModuleContext
from tests.test_boot_wiring import _bus


class _CtxMod(BaseModule):
    name = "ctx-test-mod"


def test_reading_context_before_attach_raises():
    mod = _CtxMod(_bus())
    try:
        mod.context
    except RuntimeError as exc:
        assert "ctx-test-mod" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_attached_context_is_returned():
    ctx = object()
    mod = _CtxMod(_bus())
    mod.attach_context(ctx)
    assert mod.context is ctx


def test_build_fills_the_default_services(tmp_path):
    clock = EntityClock()
    ctx = ModuleContext.build(clock)
    assert ctx.clock is clock
    assert ctx.resolve is storage_mod.resolve
    assert ctx.write_json is state_io_mod.write_json_atomic
    assert isinstance(ctx.privacy, privacy_mod.PrivacyFilter)
    sink = ctx.jsonl(tmp_path, name="x")
    assert isinstance(sink, jsonl_sink_mod.AsyncJsonlSink)


def test_every_booted_module_shares_the_cycle_clock():
    bus = _bus()
    registry = build_registry(
        bus,
        {
            "modules": {
                "interoception": True,
                "self_model": True,
                "effectors": True,
            },
            "interoception": {
                "read_interval_s": 1.0,
                "cycle_latency_target_ms": 300.0,
                "baseline_salience": 0.1,
                "alert_salience": 0.7,
            },
            "self_model": {},
            "effectors": {},
        },
    )
    modules = list(registry.all_modules())
    assert len(modules) >= 3
    for module in modules:
        assert module.context.clock is registry.entity_clock


async def test_heavy_restart_keeps_the_module_context():
    from tests.test_plugins_integration import _close_module, _supervisor

    bus = _bus()
    config = {"modules": {"self_model": True}, "self_model": {}}
    registry = build_registry(bus, config)
    module = registry.get("self_model")
    # Force the heavy (rebuild) path: a light restart keeps the same instance.
    module.holds_external_resources = lambda: True
    original = module.context
    result = await _supervisor(registry, config, bus)._restart_module("self_model")
    assert result.ok and result.path == "heavy"
    rebuilt = registry.get("self_model")
    assert rebuilt.context is original
    assert rebuilt.context.clock is registry.entity_clock
    await _close_module(rebuilt)
    await bus.close()
