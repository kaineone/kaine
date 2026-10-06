# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.utterance_outcome import (
    UtteranceOutcomeObserver,
    start_utterance_outcome_observer,
)

EXPECTED_KEYS = {
    "record_id",
    "replied",
    "reply_latency_s",
    "empatheia_deviation",
    "social_drive_delta",
    "preempted",
}

R1 = "a" * 32
R2 = "b" * 32


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class FakeClock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t


async def _xadd_external_speech(bus: AsyncBus, record_id: str, timestamp: datetime):
    fields = {
        "source": "lingua",
        "type": "external_speech",
        "salience": "0.5",
        "timestamp": timestamp.isoformat(),
        "causal_parent": "",
        "payload": json.dumps({"record_id": record_id}, separators=(",", ":")),
    }
    return await bus.client.xadd("lingua.external", fields)


def _read_records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def _wait_for_records(path, count):
    while True:
        records = _read_records(path)
        if len(records) >= count:
            return records
        await asyncio.sleep(0.01)


async def _wait_for_open(observer):
    while observer.pending_count == 0:
        await asyncio.sleep(0.01)


async def test_answered_utterance(bus, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.01)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, R1, t0)
        await bus.publish(
            Event(
                source="audition",
                type="audition.transcription",
                payload={"source_label": "live_mic", "text": "hello"},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=1.5),
            )
        )
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()

    assert len(records) == 1
    rec = records[0]
    assert set(rec.keys()) == EXPECTED_KEYS
    assert rec["record_id"] == R1
    assert rec["replied"] is True
    assert rec["preempted"] is False
    assert rec["reply_latency_s"] == pytest.approx(1.5, abs=0.05)


async def test_unanswered(bus, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    t0 = datetime.now(timezone.utc)
    start_epoch = t0.timestamp()
    clock = FakeClock(start_epoch)
    observer = UtteranceOutcomeObserver(
        bus,
        path=path,
        reply_window_s=0.3,
        poll_interval_s=0.01,
        now=clock,
    )
    await observer.start()
    try:
        await _xadd_external_speech(bus, R1, t0)
        clock.t = start_epoch + 0.5
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()

    assert len(records) == 1
    rec = records[0]
    assert set(rec.keys()) == EXPECTED_KEYS
    assert rec["record_id"] == R1
    assert rec["replied"] is False
    assert rec["reply_latency_s"] is None
    assert rec["preempted"] is False


async def test_preempted(bus, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.01)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, R1, t0)
        await _xadd_external_speech(bus, R2, t0 + timedelta(seconds=0.5))
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
        assert observer.pending_count == 1
    finally:
        await observer.stop()

    assert len(records) == 1
    rec = records[0]
    assert rec["record_id"] == R1
    assert rec["preempted"] is True
    assert rec["replied"] is False
    assert rec["reply_latency_s"] is None


async def test_non_operator_speech_is_not_reply(bus, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(
        bus, path=path, reply_window_s=0.3, poll_interval_s=0.01
    )
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, R1, t0)
        await bus.publish(
            Event(
                source="audition",
                type="audition.transcription",
                payload={"source_label": "seeded", "text": "hello"},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.1),
            )
        )
        await bus.publish(
            Event(
                source="audition",
                type="audition.transcription",
                payload={"source_label": "live_mic", "text": "   "},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.15),
            )
        )
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()

    rec = records[0]
    assert rec["record_id"] == R1
    assert rec["replied"] is False
    assert rec["preempted"] is False


async def test_empatheia_and_social_drive(bus, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.01)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await bus.publish(
            Event(
                source="thymos",
                type="thymos.state",
                payload={"drives": {"social_drive": 0.2}},
                salience=0.5,
                timestamp=t0 - timedelta(seconds=1),
            )
        )
        await _xadd_external_speech(bus, R1, t0)
        await bus.publish(
            Event(
                source="thymos",
                type="thymos.state",
                payload={"drives": {"social_drive": 0.5}},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.1),
            )
        )
        await bus.publish(
            Event(
                source="empatheia",
                type="empatheia.social_error",
                payload={"deviation_magnitude": 0.4},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.2),
            )
        )
        await bus.publish(
            Event(
                source="empatheia",
                type="empatheia.social_error",
                payload={"deviation_magnitude": 0.7},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.3),
            )
        )
        await bus.publish(
            Event(
                source="audition",
                type="audition.transcription",
                payload={"source_label": "live_mic", "text": "hi"},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.4),
            )
        )
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()

    rec = records[0]
    assert set(rec.keys()) == EXPECTED_KEYS
    assert rec["social_drive_delta"] == pytest.approx(0.3, abs=1e-9)
    assert rec["empatheia_deviation"] == pytest.approx(0.7, abs=1e-9)


async def test_no_text_in_file(bus, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.01)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, R1, t0)
        secret = "secret transcript content"
        await bus.publish(
            Event(
                source="audition",
                type="audition.transcription",
                payload={"source_label": "live_mic", "text": secret},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.1),
            )
        )
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()

    assert len(records) == 1
    assert set(records[0].keys()) == EXPECTED_KEYS
    content = path.read_text()
    assert secret not in content
    assert f'"record_id": "{R1}"' in content


async def test_shutdown_drops_open_records(bus, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(
        bus, path=path, reply_window_s=10.0, poll_interval_s=0.01
    )
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, R1, t0)
        await asyncio.wait_for(_wait_for_open(observer), timeout=1)
    finally:
        await observer.stop()

    assert _read_records(path) == []
    assert any(
        "utterance outcome: dropped 1 open record(s) at shutdown" in rec.message
        for rec in caplog.records
    )


async def test_cursors_start_at_tail(bus, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    t0 = datetime.now(timezone.utc)
    await _xadd_external_speech(bus, R1, t0)
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.01)
    await observer.start()
    try:
        await asyncio.sleep(0.2)
        assert _read_records(path) == []
        # The old utterance opened nothing either.
        assert observer.pending_count == 0
    finally:
        await observer.stop()


async def test_poison_entry_does_not_stall(bus, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.01)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, R1, t0)
        # More undecodable entries than one read returns (64): a cursor that
        # only advanced past decoded entries would re-read them forever.
        for _ in range(70):
            await bus.client.xadd("audition.out", {"garbage": "value"})
        await bus.publish(
            Event(
                source="audition",
                type="audition.transcription",
                payload={"source_label": "live_mic", "text": "hello"},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.5),
            )
        )
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()

    rec = records[0]
    assert rec["record_id"] == R1
    assert rec["replied"] is True


async def test_next_utterance_after_the_window_is_not_a_preemption(bus, tmp_path):
    """When r2 comes after r1's window has already run out (both arriving in
    one batch), r1 went unanswered; it was not preempted."""
    path = tmp_path / "outcomes.jsonl"
    t0 = datetime.now(timezone.utc)
    clock = FakeClock(t0.timestamp())
    observer = UtteranceOutcomeObserver(
        bus, path=path, reply_window_s=1.0, poll_interval_s=0.01, now=clock
    )
    await observer.start()
    try:
        await _xadd_external_speech(bus, R1, t0)
        await _xadd_external_speech(bus, R2, t0 + timedelta(seconds=5))
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()

    rec = records[0]
    assert rec["record_id"] == R1
    assert rec["preempted"] is False
    assert rec["replied"] is False


async def test_events_in_one_poll_are_handled_in_time_order(bus, tmp_path):
    """A reply to r1 and the next utterance r2 that land in the same poll are
    handled by timestamp, not by stream order: r1 was answered."""
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.3)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, R1, t0)
        await asyncio.wait_for(_wait_for_open(observer), timeout=2)
        # Both written before the next poll; lingua.external is read first.
        await _xadd_external_speech(bus, R2, t0 + timedelta(seconds=2))
        await bus.publish(
            Event(
                source="audition",
                type="audition.transcription",
                payload={"source_label": "live_mic", "text": "hello"},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=1),
            )
        )
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()

    rec = records[0]
    assert rec["record_id"] == R1
    assert rec["replied"] is True
    assert rec["preempted"] is False


async def test_existing_loose_file_is_tightened(bus, tmp_path):
    """A pre-existing outcome file with loose permissions becomes owner-only on
    the next write."""
    import os
    import stat

    path = tmp_path / "outcomes.jsonl"
    path.write_text("")
    os.chmod(path, 0o644)
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.01)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, R1, t0)
        await _xadd_external_speech(bus, R2, t0 + timedelta(seconds=0.5))
        await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


async def test_start_utterance_outcome_observer_disabled_on_error(tmp_path, caplog):
    caplog.set_level(logging.WARNING)

    class BrokenBus:
        async def last_entry_id(self, stream):
            raise RuntimeError("redis down")

    path = tmp_path / "outcomes.jsonl"
    result = await start_utterance_outcome_observer(
        BrokenBus(), path=path, poll_interval_s=0.01
    )
    assert result is None
    assert any(
        "utterance-outcome observer disabled: could not start" in rec.message
        for rec in caplog.records
    )


async def test_malformed_event_in_poll_does_not_drop_reply(bus, tmp_path, caplog):
    """A malformed thymos.state event in the same poll must not prevent a later
    operator reply from being recorded."""
    caplog.set_level(logging.DEBUG)
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=1.0)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, R1, t0)
        await _wait_for_open(observer)

        # Both events arrive before the next poll; the malformed thymos event
        # must not abort handling of the reply.
        await bus.publish(
            Event(
                source="thymos",
                type="thymos.state",
                payload={"drives": "oops"},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.1),
            )
        )
        await bus.publish(
            Event(
                source="audition",
                type="audition.transcription",
                payload={"source_label": "live_mic", "text": "hello"},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.2),
            )
        )
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()

    rec = records[0]
    assert rec["record_id"] == R1
    assert rec["replied"] is True
    assert any(
        "failed to handle thymos.out" in rec.message for rec in caplog.records
    )


async def test_invalid_record_id_is_ignored(bus, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.01)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, "../../x", t0)
        await asyncio.sleep(0.2)
    finally:
        await observer.stop()

    assert _read_records(path) == []
    assert not path.exists()
    assert any("invalid record_id" in rec.message for rec in caplog.records)


async def test_write_record_runs_off_event_loop(bus, tmp_path, monkeypatch):
    import kaine.cycle.utterance_outcome as uo

    real_to_thread = uo.asyncio.to_thread
    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func.__name__, args, kwargs))
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(uo.asyncio, "to_thread", fake_to_thread)

    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.01)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, R1, t0)
        await bus.publish(
            Event(
                source="audition",
                type="audition.transcription",
                payload={"source_label": "live_mic", "text": "hello"},
                salience=0.5,
                timestamp=t0 + timedelta(seconds=0.1),
            )
        )
        records = await asyncio.wait_for(_wait_for_records(path, 1), timeout=2)
    finally:
        await observer.stop()

    assert len(records) == 1
    assert any(
        call[0] == "_write_record_sync" and call[1][0]["record_id"] == R1
        for call in calls
    )


@pytest.mark.parametrize(
    "section,expected,should_warn,expected_type",
    [
        (None, 30.0, False, None),
        ("text", 30.0, False, None),
        ({}, 30.0, False, None),
        ({"outcome_reply_window_s": "abc"}, 30.0, True, "str"),
        ({"outcome_reply_window_s": float("nan")}, 30.0, True, "float"),
        ({"outcome_reply_window_s": float("inf")}, 30.0, True, "float"),
        ({"outcome_reply_window_s": 0}, 30.0, True, "int"),
        ({"outcome_reply_window_s": -5}, 30.0, True, "int"),
        ({"outcome_reply_window_s": True}, 30.0, True, "bool"),
        ({"outcome_reply_window_s": [1]}, 30.0, True, "list"),
        ({"outcome_reply_window_s": 12.5}, 12.5, False, None),
        ({"outcome_reply_window_s": "12.5"}, 12.5, False, None),
    ],
)
def test_reply_window_from_lingua(
    section, expected, should_warn, expected_type, caplog
):
    from kaine.cycle.utterance_outcome import reply_window_from_lingua

    caplog.set_level(logging.WARNING)
    result = reply_window_from_lingua(section)
    assert result == expected
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    if should_warn:
        assert len(warns) == 1
        msg = warns[0].getMessage()
        assert "outcome_reply_window_s must be a finite number > 0" in msg
        assert f"got {expected_type}" in msg
        assert "using 30 s" in msg
        if isinstance(section, dict) and isinstance(
            section["outcome_reply_window_s"], str
        ):
            assert section["outcome_reply_window_s"] not in msg
    else:
        assert not warns


async def test_phase_utterance_outcome_boots_despite_bad_reply_window(
    tmp_path, monkeypatch
):
    import types

    from kaine.cycle.__main__ import _start_utterance_outcome

    monkeypatch.chdir(tmp_path)

    class FakeBus:
        async def last_entry_id(self, stream):
            return "0-0"

        async def read_entries(self, stream, *, last_id, count, block_ms):
            return ([], None)

    for lingua in ({"outcome_reply_window_s": "abc"}, None):
        ctx = types.SimpleNamespace(
            kaine_config={"modules": {"lingua": True}, "lingua": lingua},
            bus=FakeBus(),
            utterance_outcome=None,
        )
        await _start_utterance_outcome(ctx)
        assert isinstance(ctx.utterance_outcome, UtteranceOutcomeObserver)
        assert ctx.utterance_outcome._reply_window_s == 30.0
        await ctx.utterance_outcome.stop()


async def test_phase_utterance_outcome_disabled_skips_observer(monkeypatch):
    import types

    from kaine.cycle.__main__ import _start_utterance_outcome

    calls = []

    async def recorder(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr(
        "kaine.cycle.__main__.start_utterance_outcome_observer", recorder
    )
    ctx = types.SimpleNamespace(
        kaine_config={
            "modules": {"lingua": False},
            "lingua": {"outcome_reply_window_s": 10},
        },
        bus=None,
        utterance_outcome=None,
    )
    await _start_utterance_outcome(ctx)
    assert ctx.utterance_outcome is None
    assert calls == []


async def test_invalid_record_id_log_does_not_emit_value(bus, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    path = tmp_path / "outcomes.jsonl"
    observer = UtteranceOutcomeObserver(bus, path=path, poll_interval_s=0.01)
    await observer.start()
    try:
        t0 = datetime.now(timezone.utc)
        await _xadd_external_speech(bus, "zz<script>", t0)
        await asyncio.sleep(0.2)
    finally:
        await observer.stop()

    assert _read_records(path) == []
    assert not path.exists()
    messages = [r.getMessage() for r in caplog.records]
    assert any("invalid record_id" in m for m in messages)
    assert all("<script>" not in m for m in messages)
