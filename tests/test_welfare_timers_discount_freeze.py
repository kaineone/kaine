# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare timers discount frozen time (KAINE)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event, validate_event
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.input_check import InputLossWatcher
from kaine.cycle.preservation_monitor import (
    WelfareProtectiveMonitor,
    WelfareResponseConfig,
)
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.evaluation.observers.welfare_observer import WelfareObserver
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


class _Mono:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _StubFM:
    """ForkManager double recording preserve_live calls without touching disk."""

    def __init__(self):
        self.calls: list[dict] = []

    async def preserve_live(
        self, registry, *, reason, label, out_root, entity_name, require_encryption=False
    ):
        self.calls.append({"reason": reason})
        from kaine.lifecycle.preservation import PreservationResult

        return PreservationResult(
            ok=True,
            preservation_id=f"pid{len(self.calls)}",
            snapshot_id=f"snap{len(self.calls)}",
            reason=reason,
            label=label,
            run_id="freeze000001",
            world_model_captured=False,
        )


class _StubIncidentLog:
    def __init__(self):
        self.records: list[dict] = []

    async def write(self, record: dict) -> None:
        self.records.append(record)


class FakeBus:
    """Minimal bus double for observer tests."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, Event]]] = {}
        self._next = 1
        self.published: list[Event] = []

    def push(self, stream: str, event: Event) -> None:
        entry_id = f"{self._next}-0"
        self._next += 1
        self.streams.setdefault(stream, []).append((entry_id, event))

    async def read_entries(self, stream, *, last_id, count, block_ms):
        entries = self.streams.get(stream, [])
        try:
            start = int(last_id.split("-")[0]) if last_id else 0
        except Exception:
            start = 0
        selected = [(eid, ev) for eid, ev in entries if int(eid.split("-")[0]) > start]
        return selected, None

    async def latest(self, stream: str):
        entries = self.streams.get(stream, [])
        return entries[-1] if entries else None

    async def publish(self, event: Event) -> None:
        self.published.append(event)


class FakeSink:
    def __init__(self):
        self.rows: list[dict] = []

    async def write(self, row: dict) -> None:
        self.rows.append(row)


def _event(source: str, type_: str, payload: dict) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def _unfrozen_clock(u: _Mono) -> UnfrozenClock:
    return UnfrozenClock(
        control_state.read_frozen_state,
        unknown_counts_as="unfrozen",
        monotonic=u,
    )


async def _push_soma(bus: AsyncBus, prediction_error: float, warmup_active: bool = False):
    await bus.publish(
        validate_event(
            source="soma",
            type="soma.report",
            payload={"prediction_error": prediction_error, "warmup_active": warmup_active},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )


async def _push_gray_zone(bus: AsyncBus, category: str):
    await bus.publish(
        validate_event(
            source="welfare",
            type="welfare.gray_zone",
            payload={"gray_zone_event": category},
            salience=0.8,
            timestamp=datetime.now(timezone.utc),
        )
    )


def _make_monitor(bus, cfg, u: _Mono, wall: _Mono | None = None, incident_log=None):
    if wall is None:
        wall = _Mono(0.0)
    return WelfareProtectiveMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=cfg,
        bus=bus,
        incident_log=incident_log or IncidentLog(enabled=False, path="unused"),
        clock=wall,
        unfrozen_clock=_unfrozen_clock(u),
    )


# ---------------------------------------------------------------------------
# Protective monitor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_sustained_distress_pauses_during_freeze(bus):
    """A freeze in the middle of a sustained-distress episode stops the timer;
    the episode resumes from its accumulated unfrozen duration once released."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
    )
    u = _Mono(0.0)
    mon = _make_monitor(bus, cfg, u)
    stop = asyncio.Event()

    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)
    assert mon._fork_manager.calls == []

    control_state.freeze(reason="test", source="operator")
    # 60 s of frozen wall time: unfrozen clock must not advance.
    await mon._poll_once(stop)
    assert mon._fork_manager.calls == []

    control_state.stand_down(source="operator")
    u.value = 30.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1


@pytest.mark.asyncio
async def test_monitor_sustained_distress_resumes_after_release(bus):
    """High samples keep arriving during a freeze; after release they resume
    the existing episode and cross once the unfrozen duration elapses."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
    )
    u = _Mono(0.0)
    mon = _make_monitor(bus, cfg, u)
    stop = asyncio.Event()

    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)

    control_state.freeze(reason="test", source="operator")
    for _ in range(3):
        await _push_soma(bus, 0.9)
        await mon._poll_once(stop)
    assert mon._fork_manager.calls == []

    u.value = 30.0
    control_state.stand_down(source="operator")
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1


@pytest.mark.asyncio
async def test_monitor_low_sample_during_freeze_resets_sustained_timer(bus):
    """A below-threshold sample received while frozen resets the episode, so a
    pre-freeze onset does not fire after release without a new high sample."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
    )
    u = _Mono(0.0)
    mon = _make_monitor(bus, cfg, u)
    stop = asyncio.Event()

    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)

    control_state.freeze(reason="test", source="operator")
    await _push_soma(bus, 0.0)
    await mon._poll_once(stop)

    control_state.stand_down(source="operator")
    u.value = 30.0
    await mon._poll_once(stop)
    assert mon._fork_manager.calls == []


@pytest.mark.asyncio
async def test_monitor_gray_zone_counts_during_freeze(bus):
    """Gray-zone events published during a freeze still feed the windowed-repeat
    arm because that arm is event-driven, not time-driven."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        repeat_window_s=1000.0,
        repeat_threshold=2,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
    )
    u = _Mono(0.0)
    mon = _make_monitor(bus, cfg, u)
    stop = asyncio.Event()

    await _push_gray_zone(bus, "sustained_extreme_vad")
    await _push_gray_zone(bus, "unmaintained_fatigue")
    control_state.freeze(reason="test", source="operator")
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1


@pytest.mark.asyncio
async def test_monitor_warmup_not_consumed_by_freeze(bus):
    """A long freeze does not eat the cold-start warm-up window."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        warmup_s=120.0,
        warmup_ceiling_s=9999.0,
    )
    u = _Mono(0.0)
    mon = _make_monitor(bus, cfg, u)
    stop = asyncio.Event()

    # Stamp cold-start origin and enter warm-up.
    await mon._poll_once(stop)
    control_state.freeze(reason="test", source="operator")
    await mon._poll_once(stop)
    control_state.stand_down(source="operator")

    # Still inside the warm-up window; a high sample is drained, not counted.
    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)
    assert mon._fork_manager.calls == []

    u.value = 30.0
    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)
    assert mon._fork_manager.calls == []

    # Past the warm-up: a new onset and sustained duration fire.
    u.value = 130.0
    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)
    u.value = 160.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1


@pytest.mark.asyncio
async def test_monitor_corrupt_control_file_counts_and_records_once(bus, tmp_path):
    """A corrupt control file is treated as unknown; welfare timers keep counting
    and exactly one unreadable incident is written."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
    )
    u = _Mono(0.0)
    stub = _StubIncidentLog()
    mon = _make_monitor(bus, cfg, u, incident_log=stub)
    stop = asyncio.Event()

    (tmp_path / "control.json").write_text("{not json")
    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)
    assert len(stub.records) == 1
    assert stub.records[0]["kind"] == "freeze_state_unreadable"

    u.value = 30.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1

    # No new unknown episode -> no new unreadable-state incident (the
    # protective response above writes its own, different incident).
    await mon._poll_once(stop)
    unreadable = [r for r in stub.records if r.get("kind") == "freeze_state_unreadable"]
    assert len(unreadable) == 1


# ---------------------------------------------------------------------------
# Welfare observer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observer_extreme_vad_pauses_during_freeze():
    u = _Mono(0.0)
    sink = FakeSink()
    obs = WelfareObserver(
        FakeBus(),
        sink,
        maintenance_window_s=9999.0,
        extreme_vad_threshold=0.5,
        extreme_vad_duration_s=60.0,
        consolidation_window_s=9999.0,
        replay_rate_threshold=9999,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )

    await obs._handle_thymos(
        "1-0",
        _event(
            "thymos",
            "thymos.state",
            {"state": {"valence": -0.9, "arousal": 0.9}},
        ),
    )
    control_state.freeze(reason="test", source="operator")
    await obs._tick()
    assert not any(
        r.get("gray_zone_event") == "sustained_extreme_vad" for r in sink.rows
    )

    control_state.stand_down(source="operator")
    u.value = 60.0
    await obs._tick()
    assert any(
        r.get("gray_zone_event") == "sustained_extreme_vad" for r in sink.rows
    )


@pytest.mark.asyncio
async def test_observer_fatigue_pauses_during_freeze():
    u = _Mono(0.0)
    sink = FakeSink()
    obs = WelfareObserver(
        FakeBus(),
        sink,
        maintenance_window_s=60.0,
        extreme_vad_threshold=0.9,
        extreme_vad_duration_s=9999.0,
        consolidation_window_s=9999.0,
        replay_rate_threshold=9999,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )

    await obs._handle_soma(
        "1-0",
        _event("soma", "soma.fatigue", {"value": 105.0, "threshold": 100.0}),
    )
    control_state.freeze(reason="test", source="operator")
    await obs._tick()
    assert not any(
        r.get("gray_zone_event") == "unmaintained_fatigue" for r in sink.rows
    )

    control_state.stand_down(source="operator")
    u.value = 60.0
    await obs._tick()
    assert any(
        r.get("gray_zone_event") == "unmaintained_fatigue" for r in sink.rows
    )


@pytest.mark.asyncio
async def test_observer_corrupt_control_file_counts_and_records_once(tmp_path):
    (tmp_path / "control.json").write_text("{not json")
    u = _Mono(0.0)
    sink = FakeSink()
    obs = WelfareObserver(
        FakeBus(),
        sink,
        maintenance_window_s=9999.0,
        extreme_vad_threshold=0.9,
        extreme_vad_duration_s=9999.0,
        consolidation_window_s=9999.0,
        replay_rate_threshold=9999,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )

    await obs._handle_soma(
        "1-0",
        _event("soma", "soma.fatigue", {"value": 105.0, "threshold": 100.0}),
    )
    await obs._tick()
    await obs._tick()
    await obs._tick()

    diagnostics = [
        r for r in sink.rows if r.get("diagnostic") == "freeze_state_unreadable"
    ]
    assert len(diagnostics) == 1
    assert diagnostics[0]["unknown_episodes"] == 1
    assert obs.freeze_clock_diagnostic["unknown_episodes"] == 1


# ---------------------------------------------------------------------------
# Input-loss watcher
# ---------------------------------------------------------------------------


class _SimpleBus:
    def __init__(self, latest_return=None):
        self._latest = latest_return

    async def latest(self, stream: str):
        return self._latest


@pytest.mark.asyncio
async def test_input_loss_watcher_staleness_pauses_during_freeze(tmp_path):
    """Inputs go silent and the operator freezes the cycle for 5x the threshold:
    no notice. After release the silence keeps growing in unfrozen time, and a
    loss that persists is reported once it passes the threshold."""
    u = _Mono(0.0)
    calls: list[None] = []
    watcher = InputLossWatcher(
        _SimpleBus(("1-0", None)),
        ["topos.out"],
        threshold_s=1.0,
        poll_s=0.01,
        on_loss=lambda: calls.append(None) or None,  # type: ignore[arg-type,return-value]
        unfrozen_clock=_unfrozen_clock(u),
    )
    await watcher._baseline()

    control_state.freeze(reason="test", source="operator")
    for t_s in (0.5, 1.5, 3.0, 5.0):  # frozen: silence does not grow
        u.value = t_s
        assert not await watcher._poll_once(0)
    assert not calls

    control_state.stand_down(source="operator")
    u.value = 5.5
    assert not await watcher._poll_once(0)  # the release poll itself adds nothing
    u.value = 6.2
    assert not await watcher._poll_once(0)  # 0.7 s of unfrozen silence
    u.value = 6.9
    assert await watcher._poll_once(0)  # 1.4 s of unfrozen silence
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# UnfrozenClock primitives
# ---------------------------------------------------------------------------


def test_unfrozen_clock_requires_unknown_counts_as():
    with pytest.raises(TypeError):
        UnfrozenClock(lambda: False)


def test_unfrozen_clock_rejects_invalid_policy():
    with pytest.raises(ValueError):
        UnfrozenClock(lambda: False, unknown_counts_as="maybe")


def test_unfrozen_clock_frozen_policy_does_not_count_unknown():
    mono = _Mono(0.0)
    clock = UnfrozenClock(lambda: None, unknown_counts_as="frozen", monotonic=mono)
    mono.value = 0.0
    clock.now()
    mono.value = 1.0
    assert clock.now() == 0.0
    mono.value = 2.0
    assert clock.now() == 0.0


def test_unfrozen_clock_unfrozen_policy_counts_unknown():
    mono = _Mono(0.0)
    clock = UnfrozenClock(lambda: None, unknown_counts_as="unfrozen", monotonic=mono)
    mono.value = 0.0
    clock.now()
    mono.value = 1.0
    assert clock.now() == pytest.approx(1.0)
    mono.value = 2.0
    assert clock.now() == pytest.approx(2.0)


def test_unfrozen_clock_one_warning_per_episode(caplog):
    caplog.set_level(logging.WARNING)
    mono = _Mono(0.0)
    reads = [None, None, False, None, None]

    def read():
        return reads.pop(0)

    clock = UnfrozenClock(read, unknown_counts_as="unfrozen", monotonic=mono, poll_s=0.0)
    for t in (0.0, 1.0, 2.0, 3.0, 4.0):
        mono.value = t
        clock.now()

    warnings = [r for r in caplog.records if "freeze state unreadable" in r.message]
    assert len(warnings) == 2


def test_unfrozen_clock_span_starting_frozen_does_not_count():
    mono = _Mono(0.0)
    states = iter([True, False, False])
    clock = UnfrozenClock(
        lambda: next(states), unknown_counts_as="unfrozen", monotonic=mono, poll_s=0.0
    )
    mono.value = 0.0
    clock.now()
    mono.value = 1.0
    assert clock.now() == 0.0
    mono.value = 2.0
    assert clock.now() == 1.0


def test_unfrozen_clock_read_cache_respects_poll_s():
    mono = _Mono(0.0)
    calls = [0]

    def read():
        calls[0] += 1
        return False

    clock = UnfrozenClock(read, unknown_counts_as="unfrozen", monotonic=mono, poll_s=1.0)
    mono.value = 0.0
    clock.now()
    mono.value = 0.5
    clock.now()
    assert calls[0] == 1
    mono.value = 1.5
    clock.now()
    assert calls[0] == 2


def test_unfrozen_clock_raising_reader_counts_as_unknown():
    mono = _Mono(0.0)

    def boom():
        raise RuntimeError("boom")

    clock = UnfrozenClock(boom, unknown_counts_as="unfrozen", monotonic=mono, poll_s=0.0)
    mono.value = 0.0
    clock.now()
    assert clock.frozen() is None
    mono.value = 1.0
    assert clock.now() == pytest.approx(1.0)


def test_default_clocks_count_unknown_as_unfrozen(bus):
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=1.0,
    )
    mon = WelfareProtectiveMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=cfg,
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
    )
    assert mon._unfrozen.unknown_counts_as == "unfrozen"

    obs = WelfareObserver(FakeBus(), FakeSink())
    assert obs._unfrozen.unknown_counts_as == "unfrozen"

    watcher = InputLossWatcher(FakeBus(), ["x"], threshold_s=1.0, on_loss=lambda: None)
    assert watcher._unfrozen.unknown_counts_as == "unfrozen"
