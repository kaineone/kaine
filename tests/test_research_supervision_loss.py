# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Loss of supervision escalates in a research run, at both sites.

Site 1, ``_run_until_stopped``: a supervisor task that never started or ended
early. Site 2, the supervisor built by ``_phase_supervisor``: a poll loop that
raises (``escalate_on_crash``). In research and unattended mode both preserve
the entity (final snapshot), shut every module down and write
``escalation.json``; the caretaker is told at shutdown. An operator-present
boot does neither.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import kaine.cycle.__main__ as cyc
from kaine.cycle.boot_context import BootContext
from kaine.cycle.supervisor import SupervisorConfig
from kaine.lifecycle.manager import ForkManager
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
from kaine.storage import resolve

pytestmark = pytest.mark.asyncio


class _Bus:
    def __init__(self) -> None:
        self.closed = False

    async def publish(self, event=None):
        return "0-0"

    async def current_workspace_id(self):
        return "0-0"

    async def close(self):
        self.closed = True


class _Tracked(BaseModule):
    name = "tracked"

    def __init__(self, bus):
        super().__init__(bus)
        self.shutdown_calls = 0

    async def initialize(self):
        pass

    def serialize(self):
        return {"probe": True}

    async def shutdown(self):
        self.shutdown_calls += 1


class _Caretaker:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def send_event(self, event):
        self.events.append(event)

    async def stop(self):
        pass


class _Cycle:
    tick_index = 0
    is_paused = False

    async def shutdown(self):
        pass


def _ctx(tmp_path, mode: str) -> BootContext:
    bus = _Bus()
    registry = ModuleRegistry()
    module = _Tracked(bus)
    registry.register(module)
    cfg = SupervisorConfig.from_section(
        {
            "enabled": True,
            "poll_interval_s": 60.0,
            "incident_log": {"path": str(tmp_path / "incidents")},
        }
    )
    ctx = BootContext(
        supervision_mode=mode,
        kaine_config={},
        registry=registry,
        fork_manager=ForkManager(tmp_path / "forks"),
        supervisor_cfg=cfg,
        rebuild_module=lambda name: (_ for _ in ()).throw(RuntimeError("no rebuild")),
        bus=bus,
        cycle=_Cycle(),
    )
    ctx.stop_event = asyncio.Event()
    return ctx


def _escalation() -> dict:
    path = resolve(Path("state/cycle/escalation.json"))
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _snapshots(tmp_path) -> list:
    return [p for p in (tmp_path / "forks").rglob("*") if p.is_file()]


@pytest.mark.parametrize("mode", ["research", "unattended"])
async def test_a_crashed_poll_loop_preserves_and_escalates(tmp_path, mode):
    """Site 2: the supervisor the boot builds escalates before it halts."""
    ctx = _ctx(tmp_path, mode)
    await cyc._phase_supervisor(ctx)

    async def crashing_poll(stop_event):
        raise RuntimeError("poll loop fault")

    ctx.supervisor._poll_once = crashing_poll
    await ctx.supervisor.run(ctx.stop_event)

    assert ctx.supervisor.escalated
    assert ctx.stop_event.is_set()
    rec = _escalation()
    assert rec.get("escalated") is True
    assert rec.get("module") == "supervisor"
    assert rec.get("snapshot_id")
    assert _snapshots(tmp_path), "the final snapshot was not written"
    assert ctx.registry.get("tracked").shutdown_calls >= 1


async def test_an_operator_present_poll_crash_does_not_escalate(tmp_path):
    ctx = _ctx(tmp_path, "operator")
    await cyc._phase_supervisor(ctx)

    async def crashing_poll(stop_event):
        raise RuntimeError("poll loop fault")

    ctx.supervisor._poll_once = crashing_poll
    await ctx.supervisor.run(ctx.stop_event)

    assert ctx.stop_event.is_set()
    assert _escalation().get("escalated") is not True
    assert not _snapshots(tmp_path)
    assert ctx.registry.get("tracked").shutdown_calls == 0


async def _never_ending() -> None:
    await asyncio.Event().wait()


async def _raises() -> None:
    raise RuntimeError("supervision task fault")


@pytest.mark.parametrize("mode", ["research", "unattended"])
async def test_a_supervision_task_that_raised_escalates_and_tells_the_caretaker(tmp_path, mode):
    """Site 1: the run loop escalates when the supervisor task ended early."""
    ctx = _ctx(tmp_path, mode)
    await cyc._phase_supervisor(ctx)
    ctx.caretaker = _Caretaker()
    ctx._caretaker_tasks = set()
    ctx.cycle_task = asyncio.create_task(_never_ending())
    ctx.supervisor_task = asyncio.create_task(_raises())
    await asyncio.sleep(0)
    assert ctx.supervisor_task.done()

    await asyncio.wait_for(cyc._run_until_stopped(ctx), timeout=5.0)

    assert ctx.stop_event.is_set()
    assert ctx.supervisor.escalated
    rec = _escalation()
    assert rec.get("escalated") is True and rec.get("module") == "supervisor"
    assert _snapshots(tmp_path)

    ctx.freeze_task = asyncio.create_task(asyncio.sleep(0))
    await cyc._shutdown(ctx)
    assert ctx.caretaker.events == ["supervision_lost"]
    assert ctx.registry.get("tracked").shutdown_calls >= 1


async def test_a_supervision_task_that_never_started_escalates_in_research(tmp_path):
    ctx = _ctx(tmp_path, "research")
    await cyc._phase_supervisor(ctx)
    ctx.cycle_task = asyncio.create_task(_never_ending())
    ctx.supervisor_task = None

    await asyncio.wait_for(cyc._run_until_stopped(ctx), timeout=5.0)

    assert ctx.supervisor.escalated
    assert _escalation().get("escalated") is True
    ctx.cycle_task.cancel()


async def test_an_operator_present_run_loop_does_not_escalate(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "operator")
    await cyc._phase_supervisor(ctx)
    ctx.caretaker = None
    ctx.cycle_task = asyncio.create_task(_never_ending())
    ctx.supervisor_task = asyncio.create_task(_raises())
    await asyncio.sleep(0)

    written: list[dict] = []

    async def fake_runtime_state(*a, **k):
        written.append(k)
        ctx.stop_event.set()

    monkeypatch.setattr(cyc, "_write_runtime_state", fake_runtime_state)
    ctx.gate_runner = SimpleNamespace(stage=None, status=None)
    ctx.staging_enabled = False

    await asyncio.wait_for(cyc._run_until_stopped(ctx), timeout=5.0)

    assert written, "the operator-present loop ran its normal iteration"
    assert not ctx.supervisor.escalated
    assert _escalation().get("escalated") is not True
    assert not _snapshots(tmp_path)
    ctx.cycle_task.cancel()
    assert isinstance(ctx.supervisor_task.exception(), RuntimeError)


async def test_both_sites_use_the_same_mode_rule():
    assert cyc._supervision_loss_escalates("research") is True
    assert cyc._supervision_loss_escalates("unattended") is True
    assert cyc._supervision_loss_escalates("operator") is False
    assert cyc._supervision_loss_escalates(None) is False
