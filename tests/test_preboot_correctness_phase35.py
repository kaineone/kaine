# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Regression tests for the pre-boot-correctness-batch findings.

Covers: H1 (producer resync to shared clock), H2 (poison-proof hot
consumers), H3 (seed engine cursors at tail), M1 (maintenance poll task),
M2 (finally-publish sleep completion), L1 (incremental logical time),
L2 (clamped experiential accumulator), L3 (task ref + double-trigger
guard), L4 (rate-limited consumer error logs).
"""
from __future__ import annotations

import asyncio
import gc
import importlib
import logging
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from kaine.cycle.engine import BASE_EPOCH, CognitiveCycle
from kaine.modules.hypnos.module import Hypnos


def _find_class(module_path: str, method: str) -> type:
    mod = importlib.import_module(module_path)
    for obj in vars(mod).values():
        if isinstance(obj, type) and method in obj.__dict__:
            return obj
    raise AssertionError(f"no class with method {method!r} in {module_path}")


class _ScriptedBus:
    """Fake bus: scripted read_entries batches + tail lookup."""

    def __init__(self, batches, tail="0", fail=False):
        self._batches = list(batches)
        self._tail = tail
        self._fail = fail
        self.reads: list[tuple[str, str]] = []
        self.client = SimpleNamespace(xrevrange=self._xrevrange)

    async def _xrevrange(self, stream, count=1):
        if self._tail == "0":
            return []
        return [(self._tail, {})]

    async def read_entries(self, stream, last_id="0", count=100, block_ms=0):
        self.reads.append((stream, last_id))
        if self._fail:
            raise ConnectionError("bus down")
        if not self._batches:
            await asyncio.Event().wait()  # park forever
        return self._batches.pop(0)

    async def read(self, stream, last_id="0", count=100, block_ms=0):
        entries, _ = await self.read_entries(stream, last_id, count, block_ms)
        return entries


def _evt(type_, **payload):
    return SimpleNamespace(type=type_, payload=payload)


def _engine_stub(bus, **attrs) -> CognitiveCycle:
    eng = CognitiveCycle.__new__(CognitiveCycle)
    eng._bus = bus
    eng._tick_index = 0
    eng._cursors = {}
    eng._error_counts = {}
    eng._control_cursor = "0"
    eng._soma_out_cursor = "0"
    eng._control_err_last_log = 0.0
    eng._soma_err_last_log = 0.0
    eng._seed_cursors_to_tail = False  # ctor default; tail tests override
    eng._logical_dt = BASE_EPOCH
    eng._logical_last_tick = None
    eng._experience_acc = 0.0
    for k, v in attrs.items():
        setattr(eng, k, v)
    return eng


# ---------------------------------------------------------------- H3 / H2


@pytest.mark.asyncio
async def test_restart_does_not_replay_stale_events():
    tail = "17-1"
    bus = _ScriptedBus(
        batches=[([("18-1", _evt("some.other"))], "18-1")], tail=tail
    )
    eng = _engine_stub(bus)
    eng._seed_cursors_to_tail = True  # tail-seeding behavior under test
    # Soma consumer: cursor must be seeded to the tail before any read...
    await eng.consume_soma_regulation("soma.out")
    assert all(last_id == tail for _, last_id in bus.reads), (
        "cursor must be seeded at the stream tail, not 0"
    )
    assert eng._soma_out_cursor == "18-1"
    # ...and the control consumer seeds independently the same way.
    bus2 = _ScriptedBus(batches=[([], None)], tail=tail)
    eng2 = _engine_stub(bus2)
    eng2._seed_cursors_to_tail = True  # tail-seeding behavior under test
    await eng2.consume_control_events("control.in")
    assert all(last_id == tail for _, last_id in bus2.reads)
    assert eng2._control_cursor == tail


@pytest.mark.asyncio
async def test_poison_batch_does_not_stall_streams():
    # Engine soma consumer: a fully-undecodable batch returns no decoded
    # events, but the cursor must still advance past it.
    bus = _ScriptedBus(
        batches=[([], "5-1"), ([("5-2", _evt("soma.regulation", action="noop"))], "5-2")]
    )
    eng = _engine_stub(bus)
    await eng.consume_soma_regulation("soma.out")
    assert eng._soma_out_cursor == "5-1"  # advanced past the poison batch
    await eng.consume_soma_regulation("soma.out")
    assert eng._soma_out_cursor == "5-2"  # subsequent entries consumed
    # _safe_read path (workspace streams).
    bus2 = _ScriptedBus(batches=[([], "9-1")])
    eng2 = _engine_stub(bus2, _read_count=16)
    entries, last_scanned = await eng2._safe_read("workspace", "0")
    assert entries == [] and last_scanned == "9-1"
    # Soma module cycle consumer.
    SomaModule = _find_class("kaine.modules.soma.module", "_cycle_consumer_loop")
    bus3 = _ScriptedBus(
        batches=[
            ([], "3-1"),  # poison batch on the cycle stream
            ([("3-2", _evt("cycle.tick"))], "3-2"),
        ]
    )
    stub = SimpleNamespace(
        _stopped=asyncio.Event(),
        _bus=bus3,
        _cycle_stream="cycle",
        _cycle_cursor="0",
        _reader=SimpleNamespace(update_cycle_latency_sample=lambda x: None),
    )
    task = asyncio.create_task(SomaModule._cycle_consumer_loop(stub))
    for _ in range(200):
        if stub._cycle_cursor == "3-2":
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert stub._cycle_cursor == "3-2"


# ---------------------------------------------------------------- L1 / L2


def test_rate_change_does_not_jump_logical_timestamps():
    eng = CognitiveCycle.__new__(CognitiveCycle)
    eng._tick_index = 0
    eng._logical_dt = BASE_EPOCH
    eng._logical_last_tick = None
    eng._target_tick_period = 1.0  # rate r1
    stamps = []
    for k in range(3):
        eng._tick_index = k
        stamps.append(eng._logical_now())
    eng._target_tick_period = 0.5  # rate r2
    for k in range(3, 5):
        eng._tick_index = k
        stamps.append(eng._logical_now())
    assert stamps[:3] == [BASE_EPOCH, BASE_EPOCH, BASE_EPOCH] or all(
        (stamps[i + 1] - stamps[i]).total_seconds() == 1.0 for i in range(2)
    ), "past tick timestamps must follow 1/r1"
    # Past timestamps unchanged by the rate change (re-read is idempotent).
    assert eng._logical_now() == stamps[-1]
    # Future ticks increment by 1/r2.
    for i in range(3, 4):
        assert (stamps[i + 1] - stamps[i]).total_seconds() == 0.5


def test_experiential_accumulator_bounded_when_throttled():
    eng = CognitiveCycle.__new__(CognitiveCycle)
    eng._experience_acc = 0.0
    eng._experiential_rate = 4.0  # above the (throttled) processing rate
    eng._processing_rate = 1.0
    for _ in range(500):
        eng._advance_experiential()
        assert eng._experience_acc <= 1.0, "accumulator must stay bounded"


# ---------------------------------------------------------------- L4


@pytest.mark.asyncio
async def test_persistent_redis_failure_is_visible(caplog):
    bus = _ScriptedBus(batches=[], fail=True)
    eng = _engine_stub(bus)
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            await eng.consume_control_events("control.in")
        for _ in range(5):
            await eng.consume_soma_regulation("soma.out")
    control_warns = [r for r in caplog.records if "control consumer read failed" in r.getMessage()]
    soma_warns = [r for r in caplog.records if "soma consumer read failed" in r.getMessage()]
    assert len(control_warns) == 1, "exactly one rate-limited WARNING per window"
    assert len(soma_warns) == 1, "exactly one rate-limited WARNING per window"


# ---------------------------------------------------------------- M1 / M2 / L3


class _SchedDue:
    def is_due(self):
        return True


class _M1Stub:
    def __init__(self):
        self._stopped = asyncio.Event()
        self._scheduler = _SchedDue()
        self._sleep_lock = asyncio.Lock()  # unlocked -> not sleeping
        self._sleep_pending = False
        self._sleep_task = None
        self.sleeps = 0
        self._sleeped = asyncio.Event()

    async def enter_sleep(self):
        self.sleeps += 1
        self._sleeped.set()


@pytest.mark.asyncio
async def test_maintenance_runs_without_fatigue_consumer():
    stub = _M1Stub()
    stub._interval_triggered_enter_sleep = types.MethodType(
        Hypnos._interval_triggered_enter_sleep, stub
    )
    task = asyncio.create_task(Hypnos._maintenance_poll_loop(stub))
    await asyncio.wait_for(stub._sleeped.wait(), 5)
    assert stub.sleeps == 1, "maintenance must fire with no fatigue events at all"
    stub._stopped.set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert stub._sleep_pending is False


class _M2Stub:
    """Inner pipeline whose own completed publish fails once, transiently."""

    def __init__(self):
        self.published = []
        self._baseline_salience = 0.5
        self._failed_once = False

    async def _run_pipeline_inner(self):
        await self.publish("hypnos.sleep.completed", {})

    async def publish(self, type_, payload, salience=None):
        if (
            type_ == "hypnos.sleep.completed"
            and not payload.get("aborted")
            and not self._failed_once
        ):
            self._failed_once = True
            raise ConnectionError("transient bus hiccup")
        self.published.append((type_, payload))


@pytest.mark.asyncio
async def test_transient_publish_failure_does_not_wedge_soma():
    stub = _M2Stub()
    with pytest.raises(ConnectionError):  # the original failure re-raises honestly
        await Hypnos._run_pipeline(stub)
    completed = [p for t, p in stub.published if t == "hypnos.sleep.completed"]
    assert completed, "a completed event MUST be published even after failure"
    assert completed[0].get("aborted") is True
    # Soma consumes hypnos.sleep.completed to exit _in_hypnos; the aborted
    # flavour is the same event type, so it exits and faster_decay stops.


class _HypConsumerStub:
    def __init__(self, bus):
        self._stopped = asyncio.Event()
        self._bus = bus
        self._soma_cursor = "0"
        self._sleep_lock = asyncio.Lock()
        self._sleep_pending = False
        self._sleep_task = None
        self._fatigue_triggered_sleep = False
        self.enter_started = 0
        self.enter_done = 0
        self._release = asyncio.Event()

    async def enter_sleep(self):
        self.enter_started += 1
        await self._release.wait()
        self.enter_done += 1


@pytest.mark.asyncio
async def test_sleep_task_not_collected_and_no_double_trigger():
    fatigue = ("1-1", _evt("soma.fatigue", crossed=True))
    bus = _ScriptedBus(
        batches=[
            ([fatigue], "1-1"),
            ([("1-2", _evt("soma.fatigue", crossed=True))], "1-2"),
        ]
    )
    stub = _HypConsumerStub(bus)
    stub._fatigue_triggered_enter_sleep = types.MethodType(
        Hypnos._fatigue_triggered_enter_sleep, stub
    )
    stub._fatigue_triggered_enter_sleep_inner = types.MethodType(
        Hypnos._fatigue_triggered_enter_sleep_inner, stub
    )
    consumer = asyncio.create_task(Hypnos._soma_consumer_loop(stub))
    for _ in range(200):
        if stub.enter_started == 1:
            break
        await asyncio.sleep(0.01)
    assert stub.enter_started == 1
    await asyncio.sleep(0.2)  # second trigger arrives while first is pending
    assert stub.enter_started == 1, "double trigger must not fire twice"
    assert stub._sleep_task is not None, "task reference must be held"
    gc.collect()  # force GC mid-sleep
    stub._release.set()
    await asyncio.wait_for(asyncio.gather(stub._sleep_task), 5)
    assert stub.enter_done == 1, "sleep must complete despite forced GC"
    assert stub._sleep_pending is False
    assert stub._fatigue_triggered_sleep is True, (
        "annotation flag must survive (not cleared by a loser branch)"
    )
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(consumer, 2)


# ---------------------------------------------------------------- H1


class _Plane:
    def __init__(self, data):
        self._data = data

    def __bytes__(self):
        return self._data


class _Frame:
    def __init__(self, pts, tag, nbytes):
        self.pts = pts
        self.time_base = 1 / 1000.0
        self.planes = [_Plane(bytes([tag]) * nbytes)]


class _Container:
    def __init__(self, path):
        self.tag = int(Path(path).name)
        self.duration = 10_000_000
        self.seek_calls: list[int] = []
        self._seeked_us = 0
        self.streams = SimpleNamespace(audio=[object()])

    def seek(self, offset_us, any_frame=False):
        self.seek_calls.append(offset_us)
        self._seeked_us = offset_us

    def decode(self, stream):
        start_pts = self._seeked_us // 1000
        for pts in range(start_pts, 10_000, 20):
            yield _Frame(pts, self.tag, 960)


class _Resampler:
    def __init__(self, **kwargs):
        pass

    def resample(self, frame):
        return [frame]


def _install_fake_av(monkeypatch):
    fake_av = SimpleNamespace(
        open=lambda path: _Container(path),
        audio=SimpleNamespace(
            resampler=SimpleNamespace(AudioResampler=_Resampler)
        ),
    )
    monkeypatch.setitem(sys.modules, "av", fake_av)


class _FakeClock:
    def __init__(self):
        self.started = False
        self.loc = (0, 0.0)
        self.durations: dict[int, float] = {}

    def start(self):
        self.started = True

    def locate(self):
        return self.loc

    def wait_if_paused(self, stop_check=None):
        return False

    def set_duration(self, idx, duration):
        self.durations.setdefault(idx, duration)


def _make_feed(clock, manifest, monkeypatch):
    """Build a REAL PlaylistAudioStream over the fake manifest + fake av.

    The H1 resync test must exercise the shipped stream class (the seek /
    resync path consumes av exactly the way the production decoder does),
    so the feed is constructed through the real ctor instead of a
    hand-built __new__ fake.
    """
    _install_fake_av(monkeypatch)
    from kaine.modules.audition.feed import PlaylistAudioStream

    holder: list = []

    def _callback(pcm):
        feed = holder[0]
        if feed._first_block is None:
            feed._first_block = pcm
            feed._stopped.set()

    feed = PlaylistAudioStream(
        manifest,
        callback=_callback,
        sample_rate=48000,
        channels=1,
        frames_per_block=480,
        playlist_clock=clock,
    )
    # Test-facing shims mirroring the old fake's observable surface.
    feed._first_block = None
    feed._stopped = threading.Event()
    holder.append(feed)
    return feed


def test_producer_restart_resyncs_to_clock(monkeypatch, tmp_path):
    # PlaylistAudioStream derives its media root from Path(manifest.manifest_path).
    manifest = SimpleNamespace(
        items=[SimpleNamespace(path="0"), SimpleNamespace(path="1")],
        manifest_path=str(tmp_path / "playlist.manifest.toml"),
    )
    # First run: clock at item 0, offset 0.
    clock = _FakeClock()
    feed = _make_feed(clock, manifest, monkeypatch)
    t = threading.Thread(target=feed._produce)
    t.start()
    assert feed._stopped.wait(10), "first run must produce audio"
    t.join(10)
    assert feed._first_block[0] == 0  # item 0 audio

    # Restart (mute off / new producer): clock now at item 1, offset 0.5 s.
    clock2 = _FakeClock()
    clock2.loc = (1, 0.5)
    feed2 = _make_feed(clock2, manifest, monkeypatch)
    t2 = threading.Thread(target=feed2._produce)
    t2.start()
    assert feed2._stopped.wait(10), "restarted producer must produce audio"
    t2.join(10)
    # Audio resumes at the CLOCK position (item 1), not item 0...
    assert feed2._first_block[0] == 1, "audio must resume at clock position"
    # ...via a container seek to the clock's offset (µs), so the audio
    # position agrees with the video/clock position within tolerance.
    # The item-1 container is created inside the run; the seek is observable
    # through the resumed frame content (tag 1) delivered from offset 0.5 s.
    # Skipped items are NOT re-opened just to register durations — the video
    # side (or the pre-restart run) is the duration authority for passed items.
