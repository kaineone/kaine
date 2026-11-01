# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Loss of the welfare monitor escalates in a research or unattended run.

The cycle's run loop watches the welfare monitor as it watches the
supervisor: a monitor never built or started, a monitor task that ended, or a
poll loop that keeps raising (three polls in a row and no poll returned for
one distress_duration_s) takes the supervision-loss path: final snapshot,
every module shut down, escalation.json naming welfare_monitor, and the
caretaker told at shutdown. An operator-present boot does not escalate, and a
run the welfare monitor itself ended is no loss.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import kaine.cycle.__main__ as cyc
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import (
    PreservationConfig,
    WelfareBusTimeout,
    WelfareProtectiveMonitor,
    WelfareResponseConfig,
)
from kaine.cycle.supervisor import WELFARE_MONITOR_ESCALATION_MODULE
from kaine.modules.registry import ModuleRegistry
from tests.test_research_supervision_loss import (
    _Caretaker,
    _ctx,
    _escalation,
    _never_ending,
    _raises,
    _snapshots,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")


def _welfare_cfg() -> PreservationConfig:
    return PreservationConfig.from_section(
        {"welfare_response": {"enabled": True, "action": "pause", "poll_interval_s": 0.01}}
    )


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _monitor(clock: _Clock, cfg: WelfareResponseConfig, *, bus=None, **kwargs) -> WelfareProtectiveMonitor:
    return WelfareProtectiveMonitor(
        registry=ModuleRegistry(),
        fork_manager=None,
        config=cfg,
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=clock,
        **kwargs,
    )


class _SilentBus:
    """A bus whose reads never answer (a half-open connection); publishes return."""

    def __init__(self) -> None:
        self.reads = 0

    async def read_entries(self, *args, **kwargs):
        self.reads += 1
        await asyncio.Event().wait()

    async def last_entry_id(self, *args, **kwargs):
        self.reads += 1
        await asyncio.Event().wait()

    async def publish(self, event=None):
        return "0-0"


async def _ctx_with_monitor(tmp_path, mode: str):
    ctx = _ctx(tmp_path, mode)
    await cyc._phase_supervisor(ctx)
    ctx.preservation_cfg = _welfare_cfg()
    ctx.caretaker = _Caretaker()
    ctx._caretaker_tasks = set()
    ctx.cycle_task = asyncio.create_task(_never_ending())
    clock = _Clock()
    ctx.welfare_monitor = _monitor(clock, ctx.preservation_cfg.welfare_response)
    return ctx, clock


def _assert_escalated(ctx, tmp_path) -> None:
    assert ctx.stop_event.is_set()
    assert ctx.supervisor.escalated
    rec = _escalation()
    assert rec.get("escalated") is True
    assert rec.get("module") == WELFARE_MONITOR_ESCALATION_MODULE
    assert rec.get("snapshot_id")
    assert _snapshots(tmp_path), "the final snapshot was not written"
    assert ctx.registry.get("tracked").shutdown_calls >= 1


@pytest.mark.parametrize("mode", ["research", "unattended"])
async def test_a_welfare_monitor_task_that_ended_escalates_and_tells_the_caretaker(tmp_path, mode):
    ctx, _clock = await _ctx_with_monitor(tmp_path, mode)
    ctx.supervisor_task = asyncio.create_task(_never_ending())
    ctx.welfare_task = asyncio.create_task(_raises())
    await asyncio.sleep(0)
    assert ctx.welfare_task.done()

    await asyncio.wait_for(cyc._run_until_stopped(ctx), timeout=5.0)

    _assert_escalated(ctx, tmp_path)
    ctx.freeze_task = asyncio.create_task(asyncio.sleep(0))
    ctx.supervisor_task.cancel()
    await cyc._shutdown(ctx)
    assert ctx.caretaker.events == ["supervision_lost"]
    ctx.cycle_task.cancel()


async def test_a_welfare_monitor_task_that_never_started_escalates(tmp_path):
    ctx, _clock = await _ctx_with_monitor(tmp_path, "research")
    ctx.supervisor_task = asyncio.create_task(_never_ending())
    ctx.welfare_task = None
    await asyncio.wait_for(cyc._run_until_stopped(ctx), timeout=5.0)
    _assert_escalated(ctx, tmp_path)
    ctx.supervisor_task.cancel()
    ctx.cycle_task.cancel()


async def test_a_welfare_response_with_no_monitor_built_escalates(tmp_path):
    ctx, _clock = await _ctx_with_monitor(tmp_path, "research")
    ctx.welfare_monitor = None
    ctx.supervisor_task = asyncio.create_task(_never_ending())
    await asyncio.wait_for(cyc._run_until_stopped(ctx), timeout=5.0)
    _assert_escalated(ctx, tmp_path)
    ctx.supervisor_task.cancel()
    ctx.cycle_task.cancel()


async def test_a_poll_loop_that_keeps_raising_escalates(tmp_path):
    """The real monitor's run loop: every poll raises, the task stays alive."""
    ctx, clock = await _ctx_with_monitor(tmp_path, "research")
    ctx.supervisor_task = asyncio.create_task(_never_ending())

    async def broken_poll(stop_event):
        raise RuntimeError("welfare poll fault")

    ctx.welfare_monitor._poll_once = broken_poll
    ctx.welfare_task = asyncio.create_task(ctx.welfare_monitor.run(ctx.stop_event))
    for _ in range(500):
        if ctx.welfare_monitor.poll_failures >= 3:
            break
        await asyncio.sleep(0.01)
    assert ctx.welfare_monitor.poll_failures >= 3
    assert not ctx.welfare_task.done()
    clock.t += 31.0  # one distress_duration_s with no poll returned
    await asyncio.wait_for(cyc._run_until_stopped(ctx), timeout=5.0)
    _assert_escalated(ctx, tmp_path)
    await asyncio.wait_for(ctx.welfare_task, timeout=5.0)
    ctx.supervisor_task.cancel()
    ctx.cycle_task.cancel()


async def test_the_failing_rule_needs_three_failures_and_the_bound():
    clock = _Clock()
    monitor = _monitor(clock, WelfareResponseConfig(enabled=True))
    monitor.loop_started_at = 0.0
    monitor.poll_failures = 2
    clock.t = 100.0
    assert monitor.poll_loop_failing(30.0) is False  # two failures are not a failing loop
    monitor.poll_failures = 3
    monitor.last_poll_ok_at = 80.0
    assert monitor.poll_loop_failing(30.0) is False  # a poll returned 20 s ago
    clock.t = 110.0
    assert monitor.poll_loop_failing(30.0) is True


async def test_a_poll_that_returns_resets_the_failure_count(tmp_path):
    clock = _Clock()
    monitor = _monitor(clock, WelfareResponseConfig(enabled=True, poll_interval_s=0.01))
    calls = {"n": 0}
    stop = asyncio.Event()

    async def flaky(stop_event):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise RuntimeError("transient")
        clock.t = 5.0
        stop.set()

    monitor._poll_once = flaky
    await asyncio.wait_for(monitor.run(stop), timeout=5.0)
    assert monitor.poll_failures == 0
    assert monitor.last_poll_ok_at == 5.0


async def test_a_run_the_welfare_monitor_ended_is_no_loss(tmp_path):
    """Action "end": the monitor sets the stop event and its task returns."""
    ctx, _clock = await _ctx_with_monitor(tmp_path, "research")
    ctx.supervisor_task = asyncio.create_task(_never_ending())
    ctx.stop_event.set()
    ctx.welfare_task = asyncio.create_task(asyncio.sleep(0))
    await asyncio.sleep(0.01)
    await asyncio.wait_for(cyc._run_until_stopped(ctx), timeout=5.0)
    assert not ctx.supervisor.escalated
    assert _escalation().get("escalated") is not True
    ctx.supervisor_task.cancel()
    ctx.cycle_task.cancel()


async def test_an_operator_present_run_does_not_escalate_a_lost_monitor(tmp_path, monkeypatch):
    ctx, _clock = await _ctx_with_monitor(tmp_path, "operator")
    ctx.supervisor_task = asyncio.create_task(_never_ending())
    ctx.welfare_task = asyncio.create_task(_raises())
    await asyncio.sleep(0)

    async def fake_runtime_state(*a, **k):
        ctx.stop_event.set()

    monkeypatch.setattr(cyc, "_write_runtime_state", fake_runtime_state)
    ctx.gate_runner = SimpleNamespace(stage=None, status=None)
    ctx.staging_enabled = False
    await asyncio.wait_for(cyc._run_until_stopped(ctx), timeout=5.0)
    assert not ctx.supervisor.escalated
    assert _escalation().get("escalated") is not True
    ctx.supervisor_task.cancel()
    ctx.cycle_task.cancel()


# --- the monitor's own bus reads are bounded ----------------------------------------


@pytest.mark.parametrize("warmup_s", [0.0, 120.0])
async def test_a_bus_read_that_never_answers_fails_the_poll(warmup_s):
    """In warm-up and after it, a hung read is a failed poll, never an empty read."""
    clock = _Clock()
    bus = _SilentBus()
    monitor = _monitor(
        clock,
        WelfareResponseConfig(enabled=True, warmup_s=warmup_s, warmup_ceiling_s=0.0),
        bus=bus,
        bus_timeout_s=0.05,
    )
    with pytest.raises(WelfareBusTimeout):
        await asyncio.wait_for(monitor._poll_once(asyncio.Event()), timeout=5.0)
    assert bus.reads >= 1


async def test_a_hung_bus_read_escalates_through_the_liveness_check(tmp_path):
    """The real monitor's run loop on a bus that never answers: every poll
    fails within the bound, and the run loop escalates the lost monitor."""
    ctx, clock = await _ctx_with_monitor(tmp_path, "research")
    ctx.supervisor_task = asyncio.create_task(_never_ending())
    ctx.welfare_monitor = _monitor(
        clock, ctx.preservation_cfg.welfare_response, bus=_SilentBus(), bus_timeout_s=0.05
    )
    ctx.welfare_task = asyncio.create_task(ctx.welfare_monitor.run(ctx.stop_event))
    for _ in range(500):
        if ctx.welfare_monitor.poll_failures >= 3:
            break
        await asyncio.sleep(0.01)
    assert ctx.welfare_monitor.poll_failures >= 3
    assert not ctx.welfare_task.done()
    clock.t += 31.0
    await asyncio.wait_for(cyc._run_until_stopped(ctx), timeout=5.0)
    _assert_escalated(ctx, tmp_path)
    await asyncio.wait_for(ctx.welfare_task, timeout=5.0)
    ctx.supervisor_task.cancel()
    ctx.cycle_task.cancel()


async def test_the_monitor_never_reads_the_bus_unbounded():
    """Every bus read in the welfare monitor goes through its bounded helper."""
    import inspect

    import kaine.cycle.preservation_monitor as pm

    source = inspect.getsource(pm.WelfareProtectiveMonitor)
    for call in ("self._bus.read_entries(", "self._bus.last_entry_id("):
        for line in source.splitlines():
            if call in line:
                assert "self._bus_read(" in line, line
