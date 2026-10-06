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


def _record_into(calls: list):
    """An awaitable on_loss callback that records each call."""

    async def _on_loss() -> None:
        calls.append(None)

    return _on_loss


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
async def test_monitor_sample_before_a_60s_freeze_does_not_cross(bus):
    """A distress-level sample just before a 60 s freeze, with no further
    sample: frozen time does not count, so the 30 s duration is not reached."""
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
    await mon._poll_once(stop)  # onset at unfrozen 0
    control_state.freeze(reason="test", source="operator")
    for t_s in (1.0, 15.0, 31.0, 45.0, 60.0):  # time passes while frozen
        u.value = t_s
        await mon._poll_once(stop)
    assert mon._fork_manager.calls == []


@pytest.mark.asyncio
async def test_monitor_same_sample_without_freeze_crosses_at_30s(bus):
    """The control: the same sample with no freeze crosses once 30 s pass."""
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
    u.value = 15.0
    await mon._poll_once(stop)
    assert mon._fork_manager.calls == []
    u.value = 30.5
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1

@pytest.mark.asyncio
async def test_monitor_sustained_distress_crosses_on_wall_time_while_sampling_through_freeze(bus):
    """High samples keep arriving through a freeze, so they are evidence the
    distress persisted: the run crosses at 30 s of wall time, frozen or not."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
    )
    u = _Mono(0.0)
    # One clock base: wall time is what the run measures while samples arrive.
    mon = _make_monitor(bus, cfg, u, wall=u)
    stop = asyncio.Event()

    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)  # onset at unfrozen 0
    u.value = 10.0
    await mon._poll_once(stop)  # 10 s unfrozen
    control_state.freeze(reason="test", source="operator")
    u.value = 11.0
    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)  # 11 s of wall time, sampled while frozen
    assert mon._fork_manager.calls == []
    u.value = 29.0
    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)  # 29 s
    assert mon._fork_manager.calls == []
    u.value = 30.5
    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)  # 30.5 s of wall time: crosses while still frozen
    assert len(mon._fork_manager.calls) == 1
    control_state.stand_down(source="operator")

@pytest.mark.asyncio
async def test_monitor_low_sample_during_freeze_resets_sustained_timer(bus):
    """A below-threshold sample received while frozen resets the run, so the
    pre-freeze onset never crosses after release without a new high sample."""
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
    u.value = 5.0
    await _push_soma(bus, 0.0)
    await mon._poll_once(stop)
    control_state.stand_down(source="operator")
    for t_s in (6.0, 40.0, 80.0):
        u.value = t_s
        await mon._poll_once(stop)
    assert mon._fork_manager.calls == []

@pytest.mark.asyncio
async def test_monitor_gray_zone_counts_during_freeze(bus):
    """Gray-zone events published while the cycle is frozen still feed the
    windowed-repeat arm: it is event-driven, and a crossing during a long
    freeze is never lost."""
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

    await mon._poll_once(stop)
    control_state.freeze(reason="test", source="operator")
    u.value = 5.0
    await mon._poll_once(stop)  # the freeze is observed
    await _push_gray_zone(bus, "sustained_extreme_vad")
    await _push_gray_zone(bus, "unmaintained_fatigue")
    u.value = 10.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1

@pytest.mark.asyncio
async def test_monitor_warmup_not_consumed_by_freeze(bus):
    """A 300 s freeze right after boot does not eat the 120 s warm-up."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        warmup_s=120.0,
        warmup_ceiling_s=0.0,
    )
    u = _Mono(0.0)
    mon = _make_monitor(bus, cfg, u)
    stop = asyncio.Event()

    await mon._poll_once(stop)  # warm-up origin at unfrozen 0
    control_state.freeze(reason="test", source="operator")
    for t_s in (1.0, 150.0, 300.0):
        u.value = t_s
        await mon._poll_once(stop)
    control_state.stand_down(source="operator")
    u.value = 301.0
    await mon._poll_once(stop)  # release poll adds nothing
    # Still inside the warm-up (unfrozen time is about 1 s): a sustained
    # crossing within it does not act.
    await _push_soma(bus, 0.9)
    u.value = 302.0
    await mon._poll_once(stop)
    u.value = 340.0
    await mon._poll_once(stop)  # 39 s unfrozen: past 30 s, still warm-up
    assert mon._fork_manager.calls == []
    # Past the warm-up: a new onset and sustained duration act.
    u.value = 425.0
    await _push_soma(bus, 0.9)
    await mon._poll_once(stop)  # about 124 s unfrozen
    u.value = 456.0
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
    """Extreme affect entered just before a 120 s freeze does not fire while
    frozen, and fires after 60 s of unfrozen time in total."""
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
        "1-0", _event("thymos", "thymos.state", {"state": {"valence": -0.9, "arousal": 0.9}})
    )
    control_state.freeze(reason="test", source="operator")
    for t_s in (1.0, 61.0, 120.0):
        u.value = t_s
        await obs._tick()
    assert not any(r.get("gray_zone_event") == "sustained_extreme_vad" for r in sink.rows)
    control_state.stand_down(source="operator")
    u.value = 121.0
    await obs._tick()  # release tick adds nothing
    u.value = 170.0
    await obs._tick()  # 49 s unfrozen
    assert not any(r.get("gray_zone_event") == "sustained_extreme_vad" for r in sink.rows)
    u.value = 181.5
    await obs._tick()  # 60.5 s unfrozen
    assert any(r.get("gray_zone_event") == "sustained_extreme_vad" for r in sink.rows)

@pytest.mark.asyncio
async def test_observer_fatigue_pauses_during_freeze():
    """Fatigue without maintenance is not reported for frozen time."""
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
        "1-0", _event("soma", "soma.fatigue", {"value": 105.0, "threshold": 100.0})
    )
    control_state.freeze(reason="test", source="operator")
    for t_s in (1.0, 61.0, 120.0):
        u.value = t_s
        await obs._tick()
    assert not any(r.get("gray_zone_event") == "unmaintained_fatigue" for r in sink.rows)
    control_state.stand_down(source="operator")
    u.value = 121.0
    await obs._tick()
    u.value = 170.0
    await obs._tick()
    assert not any(r.get("gray_zone_event") == "unmaintained_fatigue" for r in sink.rows)
    u.value = 181.5
    await obs._tick()
    assert any(r.get("gray_zone_event") == "unmaintained_fatigue" for r in sink.rows)

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
        on_loss=_record_into(calls),
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

    async def _noop() -> None:
        return None

    watcher = InputLossWatcher(FakeBus(), ["x"], threshold_s=1.0, on_loss=_noop)
    assert watcher._unfrozen.unknown_counts_as == "unfrozen"


# ---------------------------------------------------------------------------
# Second-review fixes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_freeze_during_warmup_capped_by_wall_ceiling(bus):
    """Integrator reproduction: a freeze at t=10 s during warm-up does not
    blind the repeat arm forever; the response fires once wall time passes
    warmup_ceiling_s, and never while warm-up still drains."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        repeat_window_s=1000.0,
        repeat_threshold=2,
        warmup_s=120.0,
        warmup_ceiling_s=300.0,
    )
    u = _Mono(0.0)
    wall = _Mono(0.0)
    mon = _make_monitor(bus, cfg, u, wall)
    stop = asyncio.Event()

    await mon._poll_once(stop)  # warm-up origin stamped at wall/u 0
    control_state.freeze(reason="test", source="operator")
    for step in range(1, 80):  # wall advances in 5 s ticks up to 395 s
        wall.value = step * 5.0
        u.value = wall.value
        if wall.value % 50.0 == 0.0:
            await _push_gray_zone(bus, "sustained_extreme_vad")
            await _push_gray_zone(bus, "unmaintained_fatigue")
        await mon._poll_once(stop)
        assert len(mon._fork_manager.calls) == 0 or wall.value >= 300.0, (
            f"fired prematurely at wall={wall.value}"
        )
    assert len(mon._fork_manager.calls) == 1


@pytest.mark.asyncio
async def test_monitor_sustained_distress_fires_by_wall_time_while_sampling_through_freeze(bus):
    """Samples keep arriving during a freeze, so the sustained run tracks
    wall time and crosses at distress_duration_s of wall time."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
    )
    u = _Mono(0.0)
    wall = _Mono(0.0)
    mon = _make_monitor(bus, cfg, u, wall)
    stop = asyncio.Event()

    await _push_soma(bus, 0.9)
    wall.value = 0.0
    u.value = 0.0
    await mon._poll_once(stop)  # onset

    control_state.freeze(reason="test", source="operator")
    for t_s in (5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0):
        wall.value = t_s
        u.value = t_s
        await _push_soma(bus, 0.9)
        await mon._poll_once(stop)
        if t_s < 30.0:
            assert mon._fork_manager.calls == []
    assert len(mon._fork_manager.calls) == 1


@pytest.mark.asyncio
async def test_observer_sustained_distress_fires_by_wall_time_while_sampling_through_freeze(
    monkeypatch,
):
    """The observer's interoceptive-distress arm also tracks wall time while
    samples keep arriving during a freeze."""
    from kaine.lifecycle.welfare_signal import SustainedThresholdTracker

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

    u.value = 0.0
    await obs._handle_soma(
        "1-0", _event("soma", "soma.report", {"prediction_error": 0.9})
    )

    control_state.freeze(reason="test", source="operator")
    for t_s in (5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0):
        u.value = t_s
        await obs._handle_soma(
            f"{int(t_s)}-0",
            _event("soma", "soma.report", {"prediction_error": 0.9}),
        )
        await obs._tick()
        if t_s < 30.0:
            assert not any(
                r.get("gray_zone_event") == "sustained_interoceptive_distress"
                for r in sink.rows
            )

    assert any(
        r.get("gray_zone_event") == "sustained_interoceptive_distress"
        for r in sink.rows
    )
    # The tracker is the shared implementation.
    assert isinstance(obs._interoceptive_distress, SustainedThresholdTracker)


async def test_observer_sustained_distress_fires_once_on_dense_unfrozen_samples(monkeypatch):
    """A sample arriving exactly at the sustain duration must emit the gray-zone
    record, even if _tick is never called between samples."""
    from kaine.lifecycle.welfare_signal import SustainedThresholdTracker

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
        interoceptive_distress_threshold=0.5,
        interoceptive_distress_duration_s=30.0,
    )

    u.value = 0.0
    await obs._handle_soma(
        "0-0", _event("soma", "soma.report", {"prediction_error": 0.9})
    )
    for t_s in range(1, 31):
        u.value = float(t_s)
        await obs._handle_soma(
            f"{t_s}-0", _event("soma", "soma.report", {"prediction_error": 0.9})
        )
        if t_s < 30:
            assert not any(
                r.get("gray_zone_event") == "sustained_interoceptive_distress"
                for r in sink.rows
            )

    distress_records = [
        r for r in sink.rows
        if r.get("gray_zone_event") == "sustained_interoceptive_distress"
    ]
    assert len(distress_records) == 1
    assert distress_records[0]["seconds_sustained"] >= 30.0
    # The tracker is the shared implementation.
    assert isinstance(obs._interoceptive_distress, SustainedThresholdTracker)


def test_tracker_elapsed_formula_counts_wall_to_last_sample_then_unfrozen():
    """A sample anchors the wall portion; only unfrozen time after the last
    sample is counted."""
    from kaine.lifecycle.welfare_signal import SustainedThresholdTracker

    tracker = SustainedThresholdTracker(threshold=0.5, duration_s=30.0)
    # Onset at unfrozen/wall 0; last sample before freeze at 10.
    assert not tracker.observe(0.9, 0.0, wall_now=0.0)
    assert not tracker.observe(0.9, 10.0, wall_now=10.0)

    # No samples during a 60 s freeze: frozen time after the last sample
    # does not count.
    assert not tracker.check_timeout(10.0)
    assert not tracker.check_timeout(10.0)

    # After release, only unfrozen time since the last sample counts.
    assert not tracker.check_timeout(29.9)
    assert tracker.check_timeout(30.0)


def test_tracker_elapsed_formula_with_samples_during_freeze():
    """Samples arriving during a freeze advance the wall-time portion."""
    from kaine.lifecycle.welfare_signal import SustainedThresholdTracker

    tracker = SustainedThresholdTracker(threshold=0.5, duration_s=30.0)
    assert not tracker.observe(0.9, 0.0, wall_now=0.0)

    # Freeze starts; unfrozen time stays at 10, but wall time advances.
    assert not tracker.observe(0.9, 10.0, wall_now=10.0)
    for wall in (15.0, 20.0, 25.0):
        assert not tracker.observe(0.9, 10.0, wall_now=wall)
    assert tracker.observe(0.9, 10.0, wall_now=30.0)


def test_tracker_without_wall_now_matches_single_clock_behavior():
    """Callers that pass one clock (wall_now defaults to now) see the same
    behavior as the original single-clock tracker."""
    from kaine.lifecycle.welfare_signal import SustainedThresholdTracker

    tracker = SustainedThresholdTracker(threshold=0.5, duration_s=30.0)
    assert not tracker.observe(0.9, 0.0)
    assert not tracker.observe(0.9, 15.0)
    assert not tracker.check_timeout(29.9)
    assert tracker.check_timeout(30.0)

    # A drop below threshold resets.
    assert not tracker.observe(0.0, 100.0)
    assert not tracker.observe(0.9, 100.0)
    assert not tracker.check_timeout(129.9)
    assert tracker.check_timeout(130.0)


@pytest.mark.asyncio
async def test_input_loss_baseline_failure_retried_and_leftover_not_fresh():
    """A failed baseline is retried; leftover entries are anchored, not
    mistaken for fresh activity, and loss is reported at the threshold."""
    class _FlakyBus:
        def __init__(self, latest_return):
            self._latest = latest_return
            self._calls = 0

        async def latest(self, stream: str):
            self._calls += 1
            if self._calls <= 1:
                raise RuntimeError("baseline boom")
            return self._latest

    u = _Mono(0.0)
    calls: list[None] = []
    watcher = InputLossWatcher(
        _FlakyBus(("1-0", None)),
        ["topos.out"],
        threshold_s=1.0,
        poll_s=0.01,
        on_loss=_record_into(calls),
        unfrozen_clock=_unfrozen_clock(u),
    )
    await watcher._baseline()  # fails
    assert "topos.out" not in watcher._baselined

    # First poll retries the baseline; the leftover entry is anchored.
    u.value = 0.2
    assert not await watcher._poll_once(0)
    assert "topos.out" in watcher._baselined
    assert not calls

    # Silence grows in unfrozen time; crosses the threshold exactly.
    u.value = 0.9
    assert not await watcher._poll_once(0)
    u.value = 1.5
    assert await watcher._poll_once(0)
    assert len(calls) == 1


def test_cycle_wiring_uses_one_shared_unfrozen_clock():
    """The cycle boot creates a single `UnfrozenClock` and passes it to both
    the welfare-protective monitor and the input-loss watcher."""
    import ast
    import inspect

    from kaine.cycle import __main__ as cycle_main

    source = inspect.getsource(cycle_main)
    tree = ast.parse(source)

    assigns = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute) and target.attr == "unfrozen_clock"
            for target in node.targets
        )
    ]
    assert len(assigns) == 1, "expected exactly one ctx.unfrozen_clock assignment"

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    monitor_call = next(
        (c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "WelfareProtectiveMonitor"),
        None,
    )
    watcher_call = next(
        (c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "InputLossWatcher"),
        None,
    )
    assert monitor_call is not None
    assert watcher_call is not None

    def uses_shared_clock(call):
        for kw in call.keywords:
            if kw.arg == "unfrozen_clock":
                return (
                    isinstance(kw.value, ast.Attribute)
                    and kw.value.attr == "unfrozen_clock"
                )
        return False

    assert uses_shared_clock(monitor_call)
    assert uses_shared_clock(watcher_call)


@pytest.mark.asyncio
async def test_monitor_zero_ceiling_means_the_soma_flag_never_extends_warmup(bus):
    """warmup_ceiling_s = 0 disables the Soma warm-up extension: a flag that
    stays set (stuck) must not hold the gate open, so sustained distress still
    crosses at its duration."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
    )
    u = _Mono(0.0)
    mon = _make_monitor(bus, cfg, u, wall=u)
    stop = asyncio.Event()
    for t_s in (0.0, 10.0, 20.0, 30.5):
        u.value = t_s
        await _push_soma(bus, 0.9, warmup_active=True)
        await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1


@pytest.mark.asyncio
async def test_monitor_freeze_cannot_stretch_the_warmup_floor_past_its_wall_bound(bus):
    """With no Soma extension (ceiling 0), a freeze that starts inside the
    warm-up floor ends warm-up at warmup_s of wall time, not never."""
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        warmup_s=120.0,
        warmup_ceiling_s=0.0,
    )
    u = _Mono(0.0)
    mon = _make_monitor(bus, cfg, u, wall=u)
    stop = asyncio.Event()
    await mon._poll_once(stop)  # stamp the start at 0
    u.value = 10.0
    control_state.freeze(reason="test", source="operator")
    t = 10.0
    while t <= 200.0:
        u.value = t
        await _push_soma(bus, 0.9)
        await mon._poll_once(stop)
        if t < 120.0:
            assert mon._fork_manager.calls == [], t
        t += 5.0
    control_state.stand_down(source="operator")
    # Warm-up ended at 120 s of wall time; sustained sampled distress then
    # crossed 30 s later, while still frozen.
    assert len(mon._fork_manager.calls) == 1
