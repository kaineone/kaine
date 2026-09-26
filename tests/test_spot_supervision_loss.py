# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
from pathlib import Path

import pytest

from kaine.cycle import escalation_state
from kaine.cycle.spot import Spot, SpotConfig
from kaine.lifecycle.manager import ForkManager
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry

pytestmark = pytest.mark.asyncio


class _DummyBus:
    async def publish(self, event=None):
        return "0-0"

    async def current_workspace_id(self):
        return "0-0"


class _TrackedModule(BaseModule):
    name = "tracked"

    def __init__(self, bus):
        super().__init__(bus)
        self.shutdown_called = False

    async def initialize(self):
        pass

    def serialize(self):
        return {}

    async def shutdown(self):
        self.shutdown_called = True


def _make_spot(tmp_path: Path, *, escalate_on_crash: bool = False):
    registry = ModuleRegistry()
    mod = _TrackedModule(_DummyBus())
    registry.register(mod)

    cfg = SpotConfig.from_section(
        {
            "enabled": True,
            "poll_interval_s": 60.0,
            "incident_log": {"path": str(tmp_path / "incidents")},
        }
    )

    fork_manager = ForkManager(tmp_path / "forks")
    spot = Spot(
        registry=registry,
        fork_manager=fork_manager,
        kaine_config={},
        config=cfg,
        rebuild_module=lambda name: (_ for _ in ()).throw(
            RuntimeError("no rebuild")
        ),
        bus=_DummyBus(),
        control_path=tmp_path / "control.json",
        escalation_path=tmp_path / "escalation.json",
        escalate_on_crash=escalate_on_crash,
    )
    return spot, mod


async def test_escalate_supervision_lost(tmp_path: Path):
    spot, mod = _make_spot(tmp_path)
    await spot.escalate_supervision_lost("supervision task ended")

    assert spot.escalated
    rec = escalation_state.read_escalation(tmp_path / "escalation.json")
    assert rec.escalated
    assert rec.module == "spot"
    assert "supervision stopped" in rec.message
    assert mod.shutdown_called


async def test_run_escalates_on_crash_when_unattended(tmp_path: Path):
    spot, _mod = _make_spot(tmp_path, escalate_on_crash=True)
    stop_event = asyncio.Event()

    async def crashing_poll(stop_event):
        raise RuntimeError("boom")

    spot._poll_once = crashing_poll

    await spot.run(stop_event)

    assert spot.escalated
    assert stop_event.is_set()
    rec = escalation_state.read_escalation(tmp_path / "escalation.json")
    assert rec.escalated
    assert rec.module == "spot"


async def test_run_does_not_escalate_on_crash_when_not_unattended(
    tmp_path: Path,
):
    spot, _mod = _make_spot(tmp_path, escalate_on_crash=False)
    stop_event = asyncio.Event()

    async def crashing_poll(stop_event):
        raise RuntimeError("boom")

    spot._poll_once = crashing_poll

    await spot.run(stop_event)

    assert spot.escalated
    assert stop_event.is_set()
    rec = escalation_state.read_escalation(tmp_path / "escalation.json")
    assert not rec.escalated
