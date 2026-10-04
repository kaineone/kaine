# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for boot follow-up fixes."""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

import kaine.boot
import kaine.cycle.__main__ as cyc
from kaine.config import ConfigShapeError, validate_config_shape
from kaine.cycle.revive_boot import REVIVE_REFUSED_EXIT, ReviveRefused


def test_failing_phase_releases_resources_and_reraises(monkeypatch):
    async def _run():
        class Bus:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        bus = Bus()
        producer_sentinel = object()
        shutdown_calls: list[object] = []
        task = asyncio.create_task(asyncio.sleep(3600))

        async def phase_one(ctx):
            ctx.bus = bus
            ctx.welfare_producer = producer_sentinel
            ctx.cycle_task = task

        async def phase_two(_ctx):
            raise RuntimeError("boom")

        original_phases = cyc._BOOT_PHASES
        cyc._BOOT_PHASES = (phase_one, phase_two)

        producer_calls: list[object] = []

        async def fake_stop(producer):
            producer_calls.append(producer)

        async def fake_shutdown(ctx):
            shutdown_calls.append(ctx)

        monkeypatch.setattr(cyc, "_stop_welfare_producer", fake_stop)
        monkeypatch.setattr(cyc, "_shutdown", fake_shutdown)

        try:
            with pytest.raises(RuntimeError, match="boom"):
                await cyc._boot_and_run(kaine_config={})
        finally:
            cyc._BOOT_PHASES = original_phases

        assert bus.closed is True
        assert producer_calls == [producer_sentinel]
        assert task.cancelled()
        assert not shutdown_calls

    asyncio.run(_run())


def test_no_modules_shutdown_on_failed_boot(monkeypatch):
    async def _run():
        shutdown_records: list[str] = []

        class Module:
            def __init__(self, name):
                self.name = name

            async def shutdown(self):
                shutdown_records.append(self.name)

        class Registry:
            def __init__(self):
                self._modules = [Module("m1"), Module("m2")]

            def all_modules(self):
                return iter(self._modules)

        async def phase_one(ctx):
            ctx.registry = Registry()

        async def phase_two(_ctx):
            raise RuntimeError("boot failure")

        original_phases = cyc._BOOT_PHASES
        cyc._BOOT_PHASES = (phase_one, phase_two)

        shutdown_called: list[bool] = []

        async def fake_shutdown(ctx):
            shutdown_called.append(True)

        monkeypatch.setattr(cyc, "_shutdown", fake_shutdown)

        try:
            with pytest.raises(RuntimeError, match="boot failure"):
                await cyc._boot_and_run(kaine_config={})
        finally:
            cyc._BOOT_PHASES = original_phases

        assert not shutdown_records
        assert not shutdown_called

    asyncio.run(_run())


def test_revive_refusal_order():
    class ReviveFake:
        async def revive(self, registry):
            raise ReviveRefused("x")

    shutdown_records: list[str] = []

    class Module:
        def __init__(self, name):
            self.name = name

        async def shutdown(self):
            shutdown_records.append(self.name)

    class Registry:
        def all_modules(self):
            return iter([Module("alpha"), Module("beta")])

    sig = inspect.signature(cyc._revive_or_refuse)
    assert list(sig.parameters) == ["revive", "registry"]

    result = asyncio.run(cyc._revive_or_refuse(ReviveFake(), Registry()))
    assert result == REVIVE_REFUSED_EXIT
    assert sorted(shutdown_records) == ["alpha", "beta"]


def test_empatheia_operator_sources_shape():
    validate_config_shape({"empatheia": {"operator_sources": ["live_mic", "manual"]}})
    validate_config_shape({"empatheia": {}})
    with pytest.raises(ConfigShapeError) as exc_info:
        validate_config_shape({"empatheia": {"operator_sources": "live_mic"}})
    assert "empatheia.operator_sources expected list of strings, got str" in str(
        exc_info.value
    )


def test_no_metrics_collector():
    assert not hasattr(kaine.boot, "MetricsCollector")
    main_path = Path(cyc.__file__).with_name("__main__.py")
    text = main_path.read_text(encoding="utf-8")
    assert "MetricsCollector" not in text


def test_vox_registry_default_is_chatterbox():
    import kaine.boot.factories.vox as vox_mod

    text = Path(vox_mod.__file__).read_text(encoding="utf-8")
    assert 'BackendRegistry[TTSClient]("vox", default="chatterbox")' in text
