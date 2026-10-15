# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Blind-sensor and sensor-silent advisories: trackers, welfare observer, and the protective monitor ignoring them."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event, validate_event
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import (
    WelfareProtectiveMonitor,
    WelfareResponseConfig,
)
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.evaluation.config import WelfareConfig
from kaine.evaluation.observers.welfare_observer import WelfareObserver
from kaine.lifecycle.welfare_signal import (
    ADVISORY_RESET,
    BLIND_SENSOR_CLEARED_TYPE,
    BLIND_SENSOR_TYPE,
    SENSOR_SILENT_CLEARED_TYPE,
    SENSOR_SILENT_TYPE,
    RunTransition,
    SilenceTracker,
    SilenceTransition,
    UndefinedRunTracker,
)
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


def _event(source: str, type_: str, payload: dict, ts: datetime | None = None) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=ts if ts is not None else datetime.now(timezone.utc),
    )


def _unfrozen_clock(u: _Mono) -> UnfrozenClock:
    return UnfrozenClock(
        control_state.read_frozen_state,
        unknown_counts_as="unfrozen",
        monotonic=u,
    )


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


def test_tracker_counts_samples_when_n_is_set():
    t = UndefinedRunTracker(min_samples=3, duration_s=30.0)
    assert t.observe(False, 0.0) is None
    assert t.observe(False, 1.0) is None
    change = t.observe(False, 2.0)
    assert change == RunTransition("raised", 3, 2.0)
    assert t.active is True
    assert t.observe(False, 3.0) is None
    clear = t.observe(True, 4.0)
    assert clear == RunTransition("cleared", 4, 4.0)
    assert t.active is False
    assert t.observe(True, 5.0) is None


def test_tracker_derives_n_from_the_duration():
    t = UndefinedRunTracker(min_samples=0, duration_s=30.0)
    assert t.observe(False, 0.0) is None
    assert t.observe(False, 10.0) is None
    assert t.observe(False, 20.0) is None
    assert t.observe(False, 29.9) is None
    change = t.observe(False, 30.0)
    assert change == RunTransition("raised", 5, 30.0)


def test_tracker_defined_sample_resets_the_run():
    t = UndefinedRunTracker(min_samples=3, duration_s=30.0)
    assert t.observe(False, 0.0) is None
    assert t.observe(False, 1.0) is None
    assert t.observe(True, 2.0) is None
    assert t.observe(False, 3.0) is None
    assert t.observe(False, 4.0) is None
    change = t.observe(False, 5.0)
    assert change == RunTransition("raised", 3, 2.0)


def test_tracker_rejects_bad_settings():
    with pytest.raises(ValueError):
        UndefinedRunTracker(min_samples=-1, duration_s=1.0)
    with pytest.raises(ValueError):
        UndefinedRunTracker(min_samples=0, duration_s=0.0)


def test_tracker_span_needs_event_time_too():
    t = UndefinedRunTracker(min_samples=0, duration_s=30.0)
    assert t.observe(False, 0.0, event_time=0.0) is None
    assert t.observe(False, 40.0, event_time=5.0) is None
    change = t.observe(False, 70.0, event_time=31.0)
    assert change == RunTransition("raised", 3, 31.0)


def test_silence_tracker_raises_and_clears():
    tracker = SilenceTracker(duration_s=30.0)
    assert tracker.check(100.0) is None
    assert tracker.seen(0.0) is None
    assert tracker.check(29.0) is None
    raised = tracker.check(30.0)
    assert raised == SilenceTransition("raised", 30.0)
    assert tracker.active is True
    assert tracker.check(60.0) is None
    cleared = tracker.seen(61.0)
    assert cleared == SilenceTransition("cleared", 61.0)
    assert tracker.active is False
    assert tracker.check(70.0) is None


@pytest.mark.asyncio
async def test_observer_raises_and_clears_a_blind_sensor_advisory():
    u = _Mono(0.0)
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        blind_sensor_samples=3,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )
    payload = {
        "prediction_error": None,
        "latent": [0.1, 0.2],
        "change_score": 0.0,
    }
    for i in range(3):
        await obs.handle(
            "vision.out",
            f"{i + 1}-0",
            _event("vision", "vision.report", payload),
        )

    assert len(bus.published) == 1
    event = bus.published[0]
    assert event.type == BLIND_SENSOR_TYPE
    assert event.source == "welfare"
    assert set(event.payload.keys()) == {
        "processor",
        "undefined_samples",
        "undefined_seconds",
        "blind_sensor_samples",
        "blind_sensor_duration_s",
        "blind_sensor_count",
    }
    assert event.payload["processor"] == "vision"
    assert event.payload["undefined_samples"] == 3
    assert not any(isinstance(v, list) for v in event.payload.values())

    assert len(sink.rows) == 1
    assert sink.rows[0]["advisory"] == "blind_sensor"
    assert obs.blind_sensor_count == 1
    assert obs.blind_sensors == ("vision",)

    await obs.handle(
        "vision.out",
        "4-0",
        _event("vision", "vision.report", payload),
    )
    await obs.handle(
        "vision.out",
        "5-0",
        _event("vision", "vision.report", {"prediction_error": 0.4}),
    )

    assert len(bus.published) == 2
    clear_event = bus.published[1]
    assert clear_event.type == BLIND_SENSOR_CLEARED_TYPE
    assert clear_event.payload["undefined_samples"] == 4
    assert obs.blind_sensors == ()
    assert obs.blind_sensor_count == 1
    assert not any(e.type == "welfare.gray_zone" for e in bus.published)


@pytest.mark.asyncio
async def test_observer_tracks_processors_separately():
    u = _Mono(0.0)
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        blind_sensor_samples=2,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )
    await obs.handle(
        "audition.out",
        "1-0",
        _event("audition", "audition.perception", {"prediction_error": None}),
    )
    await obs.handle(
        "audition.out",
        "2-0",
        _event("audition", "audition.emotion", {"prediction_error": 0.3}),
    )
    await obs.handle(
        "audition.out",
        "3-0",
        _event("audition", "audition.perception", {"prediction_error": None}),
    )
    await obs.handle(
        "audition.out",
        "4-0",
        _event("audition", "audition.emotion", {"prediction_error": 0.3}),
    )

    blind = [e for e in bus.published if e.type == BLIND_SENSOR_TYPE]
    assert len(blind) == 1
    assert blind[0].payload["processor"] == "audition_acoustic"


@pytest.mark.asyncio
async def test_observer_ignores_a_report_without_the_key_and_other_types():
    u = _Mono(0.0)
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        blind_sensor_samples=1,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )
    await obs.handle(
        "audition.out",
        "1-0",
        _event("audition", "audition.emotion", {"latent": [0.1]}),
    )
    await obs.handle(
        "audition.out",
        "2-0",
        _event("audition", "audition.transcription", {"prediction_error": None}),
    )

    assert not bus.published
    assert not sink.rows


@pytest.mark.asyncio
async def test_observer_default_n_spans_one_distress_duration():
    u = _Mono(0.0)
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        interoceptive_distress_duration_s=30.0,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )
    for t in (0.0, 15.0, 29.0):
        u.value = t
        await obs.handle(
            "interoception.out",
            "1-0",
            _event(
                "interoception",
                "interoception.report",
                {"prediction_error": None},
                ts=datetime.fromtimestamp(1_000_000.0 + t, timezone.utc),
            ),
        )

    assert not bus.published

    u.value = 30.0
    await obs.handle(
        "interoception.out",
        "2-0",
        _event(
            "interoception",
            "interoception.report",
            {"prediction_error": None},
            ts=datetime.fromtimestamp(1_000_030.0, timezone.utc),
        ),
    )

    blind = [e for e in bus.published if e.type == BLIND_SENSOR_TYPE]
    assert len(blind) == 1
    assert blind[0].payload["processor"] == "interoception"
    assert obs.sustained_interoceptive_distress_count == 0


@pytest.mark.asyncio
async def test_observer_writes_a_reset_line_and_starts_new_streams_at_the_tail():
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        blind_sensor_samples=1,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(_Mono(0.0)),
    )
    for payload in ({"prediction_error": None}, {"prediction_error": None}):
        bus.push(
            "vision.out",
            _event("vision", "vision.report", payload),
        )
    bus.push(
        "interoception.out",
        _event("interoception", "interoception.report", {"prediction_error": None}),
    )

    cursors = await obs._initial_cursors()

    assert sink.rows
    assert sink.rows[0]["advisory"] == ADVISORY_RESET
    vision_entries = bus.streams["vision.out"]
    assert cursors["vision.out"] == vision_entries[-1][0]
    assert cursors["interoception.out"] == "0"

    obs._cursors = cursors
    await obs._drain()

    assert "vision" not in obs._undefined_runs
    assert not any(e.type.startswith("welfare.") for e in bus.published)


@pytest.mark.asyncio
async def test_observer_ignores_events_from_before_its_start():
    u = _Mono(0.0)
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        blind_sensor_samples=1,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )
    obs._started_wall = datetime.now(timezone.utc)

    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    await obs.handle(
        "interoception.out",
        "1-0",
        _event("interoception", "interoception.report", {"prediction_error": None}, ts=hour_ago),
    )
    assert not bus.published

    await obs.handle(
        "interoception.out",
        "2-0",
        _event("interoception", "interoception.report", {"prediction_error": None}),
    )
    assert len(bus.published) == 1
    assert bus.published[0].type == BLIND_SENSOR_TYPE


@pytest.mark.asyncio
async def test_tracking_failure_does_not_skip_distress_handling(monkeypatch):
    u = _Mono(0.0)
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        interoceptive_distress_threshold=0.5,
        interoceptive_distress_duration_s=30.0,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )

    async def _broken_track(event):
        raise RuntimeError("tracking failure")

    monkeypatch.setattr(obs, "_track_blind_sensor", _broken_track)

    await obs.handle(
        "interoception.out",
        "1-0",
        _event("interoception", "interoception.report", {"prediction_error": 0.9}),
    )

    assert obs._interoceptive_distress.active_since is not None


@pytest.mark.asyncio
async def test_observer_raises_and_clears_a_silence_advisory():
    u = _Mono(0.0)
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        interoceptive_distress_duration_s=30.0,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )

    await obs.handle(
        "vision.out",
        "1-0",
        _event("vision", "vision.report", {"prediction_error": 0.1}),
    )

    u.value = 29.0
    await obs._tick()
    assert not any(e.type == SENSOR_SILENT_TYPE for e in bus.published)

    u.value = 30.0
    await obs._tick()
    silent = [e for e in bus.published if e.type == SENSOR_SILENT_TYPE]
    assert len(silent) == 1
    assert set(silent[0].payload.keys()) == {
        "processor",
        "silent_seconds",
        "sensor_silent_duration_s",
        "sensor_silent_count",
    }
    assert silent[0].payload["processor"] == "vision"
    assert obs.silent_sensors == ("vision",)
    assert obs.sensor_silent_count == 1

    u.value = 35.0
    await obs._tick()
    assert len([e for e in bus.published if e.type == SENSOR_SILENT_TYPE]) == 1

    await obs.handle(
        "vision.out",
        "2-0",
        _event("vision", "vision.report", {"prediction_error": 0.2}),
    )
    cleared = [e for e in bus.published if e.type == SENSOR_SILENT_CLEARED_TYPE]
    assert len(cleared) == 1
    assert obs.silent_sensors == ()


@pytest.mark.asyncio
async def test_audition_tone_is_never_silence_tracked():
    u = _Mono(0.0)
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        interoceptive_distress_duration_s=30.0,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )
    await obs.handle(
        "audition.out",
        "1-0",
        _event("audition", "audition.emotion", {"prediction_error": 0.3}),
    )
    u.value = 100.0
    await obs._tick()
    assert not bus.published


@pytest.mark.asyncio
async def test_blind_sensor_advisories_never_feed_the_protective_monitor(bus, tmp_path):
    u = _Mono(0.0)
    obs = WelfareObserver(
        bus,
        FakeSink(),
        blind_sensor_samples=1,
        poll_interval_s=0.5,
        unfrozen_clock=_unfrozen_clock(u),
    )
    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=9999.0,
        repeat_window_s=300.0,
        repeat_threshold=2,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
        out_root=str(tmp_path / "backups"),
    )
    mon = _make_monitor(bus, cfg, u)

    for _ in range(5):
        u.value += 1.0
        await obs.handle(
            "interoception.out",
            "1-0",
            _event("interoception", "interoception.report", {"prediction_error": None}),
        )
        u.value += 1.0
        await obs.handle(
            "interoception.out",
            "2-0",
            _event("interoception", "interoception.report", {"prediction_error": 0.1}),
        )

    for _ in range(2):
        u.value += 1.0
        await obs.handle(
            "vision.out",
            "3-0",
            _event("vision", "vision.report", {"prediction_error": 0.1}),
        )
        u.value += 35.0
        await obs._tick()
        await obs.handle(
            "vision.out",
            "4-0",
            _event("vision", "vision.report", {"prediction_error": 0.2}),
        )

    entries, _ = await bus.read_entries(
        "welfare.out", last_id="0", count=256, block_ms=0
    )
    advisory_types = {
        BLIND_SENSOR_TYPE,
        BLIND_SENSOR_CLEARED_TYPE,
        SENSOR_SILENT_TYPE,
        SENSOR_SILENT_CLEARED_TYPE,
    }
    assert all(e[1].type in advisory_types for e in entries)
    silence = [e for e in entries if e[1].type in (SENSOR_SILENT_TYPE, SENSOR_SILENT_CLEARED_TYPE)]
    assert len(silence) >= 4

    reasons = await mon._drain_gray_zone()
    assert reasons == []
    assert mon._repeat.count == 0

    stop = asyncio.Event()
    await mon._poll_once(stop)
    assert not mon._fork_manager.calls
    assert control_state.read_control().frozen is False

    # Positive check: real gray-zone events still trigger the monitor.
    for _ in range(2):
        await bus.publish(
            validate_event(
                source="welfare",
                type="welfare.gray_zone",
                payload={"gray_zone_event": "replay_overload"},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1


def test_welfare_config_blind_sensor_samples():
    cfg = WelfareConfig.from_mapping({})
    assert cfg.blind_sensor_samples == 0

    cfg = WelfareConfig.from_mapping({"blind_sensor_samples": 5})
    assert cfg.blind_sensor_samples == 5

    with pytest.raises(ValueError):
        WelfareConfig.from_mapping({"blind_sensor_samples": -1})
    with pytest.raises(ValueError):
        WelfareConfig.from_mapping({"blind_sensor_samples": True})
    with pytest.raises(ValueError):
        WelfareConfig.from_mapping({"blind_sensor_samples": 2.5})
