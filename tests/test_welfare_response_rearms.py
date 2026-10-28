# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The welfare response re-arms once its pause is lifted, and a welfare freeze
survives a restart."""
from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import (
    WelfareProtectiveMonitor,
    WelfareResponseConfig,
)
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.lifecycle.preservation import PreservationResult
from kaine.modules.registry import ModuleRegistry


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(control_state, "OVERRIDE_AUDIT_PATH", tmp_path / "audit.jsonl")


class _Mono:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _StubFM:
    def __init__(self):
        self.calls: list[dict] = []

    async def preserve_live(
        self, registry, *, reason, label, out_root, entity_name, require_encryption=False
    ):
        self.calls.append({"reason": reason})
        return PreservationResult(
            ok=True,
            preservation_id=f"pid{len(self.calls)}",
            snapshot_id=f"snap{len(self.calls)}",
            reason=reason,
            label=label,
            run_id="rearm0000001",
            world_model_captured=False,
        )


def _cfg(**overrides) -> WelfareResponseConfig:
    values = dict(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        repeat_window_s=1000.0,
        repeat_threshold=2,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
    )
    values.update(overrides)
    return WelfareResponseConfig(**values)


def _monitor(bus, u: _Mono, cfg=None, on_end=None) -> WelfareProtectiveMonitor:
    return WelfareProtectiveMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=cfg or _cfg(),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=u,
        on_end=on_end,
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=u
        ),
    )


async def _distress(bus: AsyncBus, error: float = 0.9) -> None:
    await bus.publish(
        validate_event(
            source="interoception",
            type="interoception.report",
            payload={"prediction_error": error, "warmup_active": False},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )


async def _gray_zone(bus: AsyncBus, category: str) -> None:
    await bus.publish(
        validate_event(
            source="welfare",
            type="welfare.gray_zone",
            payload={"gray_zone_event": category},
            salience=0.8,
            timestamp=datetime.now(timezone.utc),
        )
    )


async def _act(mon, bus, u: _Mono) -> None:
    """Drive one sustained-distress crossing: the response preserves and pauses."""
    stop = asyncio.Event()
    await _distress(bus)
    await mon._poll_once(stop)
    u.value += 31.0
    await mon._poll_once(stop)


@pytest.mark.asyncio
async def test_act_clear_rearm_act_again(bus):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    assert len(mon._fork_manager.calls) == 1
    assert "welfare" in control_state.read_holder_sources()

    # The pause is lifted by a named override.
    control_state.override(["welfare"])
    await mon._poll_once(stop)
    assert mon._acted is False

    # A new episode: the condition must accrue a full new sustained duration.
    await _distress(bus)
    await mon._poll_once(stop)
    u.value += 15.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1
    u.value += 16.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 2
    assert "welfare" in control_state.read_holder_sources()


@pytest.mark.asyncio
async def test_no_repeat_firing_while_the_pause_stands_and_the_crossing_holds(bus):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    for _ in range(6):
        u.value += 40.0
        await _distress(bus)
        await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1
    assert mon._acted is True

    # An operator resume does not lift a welfare freeze, so it does not re-arm.
    control_state.stand_down(source="operator")
    u.value += 40.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1
    assert mon._acted is True


@pytest.mark.asyncio
async def test_a_condition_still_present_at_release_fires_once_per_new_episode(bus):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    control_state.override(["welfare"])
    await mon._poll_once(stop)  # re-armed
    # Distress never lets up. Each poll feeds a sample; the response acts again
    # only after a full sustained duration, then latches until the next release.
    for _ in range(10):
        u.value += 10.0
        await _distress(bus)
        await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 2


@pytest.mark.asyncio
async def test_events_published_while_frozen_do_not_fire_after_release(bus):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    # Two gray-zone events (the repeat threshold) arrive during the pause.
    await _gray_zone(bus, "sustained_extreme_vad")
    await _gray_zone(bus, "unmaintained_fatigue")
    await _distress(bus)
    control_state.override(["welfare"])
    for _ in range(3):
        u.value += 5.0
        await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1
    assert mon._acted is False


@pytest.mark.asyncio
async def test_an_unreadable_control_file_is_not_a_release(bus, tmp_path):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    (tmp_path / "control.json").write_text("{not json")
    assert control_state.read_holder_sources() is None
    await mon._poll_once(stop)
    assert mon._acted is True


@pytest.mark.asyncio
async def test_an_end_never_rearms(bus):
    u = _Mono(0.0)
    ended: list[bool] = []
    mon = _monitor(bus, u, cfg=_cfg(action="end"), on_end=lambda: ended.append(True))
    stop = asyncio.Event()

    await _act(mon, bus, u)
    assert ended == [True]
    await mon._poll_once(stop)
    await mon._poll_once(stop)
    assert mon._acted is True
    assert len(mon._fork_manager.calls) == 1


@pytest.mark.asyncio
async def test_a_standing_welfare_freeze_from_an_earlier_process_latches_then_rearms(bus):
    control_state.freeze(reason="welfare: sustained_distress", source="welfare")
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _distress(bus)
    await mon._poll_once(stop)
    u.value += 60.0
    await mon._poll_once(stop)
    assert mon._acted is True
    assert mon._fork_manager.calls == []

    control_state.override(["welfare"])
    await mon._poll_once(stop)
    assert mon._acted is False


# ---- A welfare freeze survives a restart -----------------------------------


def test_boot_unfreeze_keeps_only_the_welfare_freeze():
    for source in ("operator", "supervisor", "development", "programme_end", "preserve"):
        control_state.push_freeze(reason="x", source=source)
    control_state.push_freeze(reason="distress", source="welfare")

    state = control_state.unfreeze_for_boot()
    assert [e["source"] for e in state.stack] == ["welfare"]
    assert state.frozen is True

    # Only a named override lifts it.
    control_state.override(["welfare"])
    assert control_state.unfreeze_for_boot().stack == ()


@pytest.mark.asyncio
async def test_the_cycle_boot_does_not_lift_a_welfare_freeze(monkeypatch):
    from kaine.cycle import __main__ as cycle_main

    monkeypatch.setattr(cycle_main, "clear_escalation", lambda: None)
    control_state.push_freeze(reason="x", source="operator")
    control_state.push_freeze(reason="distress", source="welfare")
    try:
        await cycle_main._phase_signals(SimpleNamespace(registry={}))
    finally:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
    assert control_state.read_holder_sources() == frozenset({"welfare"})


def test_the_control_cli_lifts_a_welfare_freeze_by_name(capsys):
    from kaine.cycle import control

    control_state.push_freeze(reason="distress", source="welfare")
    control_state.push_freeze(reason="x", source="operator")
    assert control.run_override(["welfare"]) == 0
    assert "still frozen by: operator" in capsys.readouterr().out
    assert control_state.read_holder_sources() == frozenset({"operator"})
    # A second override finds nothing to lift and says so.
    assert control.run_override(["welfare"]) == 1
    assert "Override refused" in capsys.readouterr().out
