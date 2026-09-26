# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
from pathlib import Path

import pytest

from kaine.cycle.caretaker import CaretakerConfig, ChannelResult
from kaine.cycle.caretaker_runtime import CaretakerNotifier, send_event_best_effort
from kaine.cycle.caretaker_state import CaretakerAck, read_start, write_ack
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


@pytest.fixture(autouse=True)
def _disable_state_encryption(tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


def _valid_config(**overrides):
    # Built directly (not via from_section) so tests can use reminder intervals
    # shorter than the 900 s minimum the config validator enforces.
    import dataclasses

    base = CaretakerConfig.from_section({"channels": [{"kind": "desktop"}]})
    return dataclasses.replace(base, **overrides)


def _make_notify(captured):
    def notify_fn(config, notice, *, secrets_path=None):
        captured.append(notice["event"])
        return [ChannelResult(kind="desktop", accepted=True, detail="")]

    return notify_fn


def _read_log(log_dir: Path):
    records = []
    for path in sorted(log_dir.glob("caretaker-*.jsonl")):
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _notifier(tmp_path, config, notify_fn, clock):
    return CaretakerNotifier(
        config,
        start_path=tmp_path / "start.json",
        ack_path=tmp_path / "ack.json",
        log_path=str(tmp_path / "caretaker"),
        notify_fn=notify_fn,
        poll_s=0.005,
        clock=clock,
    )


async def test_start_writes_start_file_and_log(tmp_path):
    clock = FakeClock(0.0)
    captured = []
    notifier = _notifier(tmp_path, _valid_config(), _make_notify(captured), clock)
    start_id = await notifier.start()
    start = read_start(path=notifier._start_path)
    assert start is not None
    assert start.start_id == start_id
    assert isinstance(start.started_at, str)
    await notifier.stop()
    log = _read_log(tmp_path / "caretaker")
    assert any(
        r.get("transition") == "start" and r.get("start_id") == start_id for r in log
    )


async def test_no_reminder_before_deadline(tmp_path):
    clock = FakeClock(0.0)
    captured = []
    notifier = _notifier(
        tmp_path, _valid_config(reminder_interval_s=10.0), _make_notify(captured), clock
    )
    await notifier.start()
    stop = asyncio.Event()
    task = asyncio.create_task(notifier.run(stop))
    clock.value = 9.0
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    await notifier.stop()
    assert captured == []


async def test_reminder_at_deadline_and_next_interval(tmp_path):
    clock = FakeClock(0.0)
    captured = []
    notifier = _notifier(
        tmp_path, _valid_config(reminder_interval_s=10.0), _make_notify(captured), clock
    )
    await notifier.start()
    stop = asyncio.Event()
    task = asyncio.create_task(notifier.run(stop))

    clock.value = 10.0
    await asyncio.sleep(0.05)
    assert captured == ["reminder"]

    clock.value = 15.0
    await asyncio.sleep(0.05)
    assert captured == ["reminder"]

    clock.value = 20.0
    await asyncio.sleep(0.05)
    assert captured == ["reminder", "reminder"]

    stop.set()
    await asyncio.wait_for(task, timeout=5)
    await notifier.stop()


async def test_acknowledgement_stops_reminders_and_logs_once(tmp_path):
    clock = FakeClock(0.0)
    captured = []
    notifier = _notifier(
        tmp_path, _valid_config(reminder_interval_s=10.0), _make_notify(captured), clock
    )
    await notifier.start()
    stop = asyncio.Event()
    task = asyncio.create_task(notifier.run(stop))

    clock.value = 10.0
    await asyncio.sleep(0.05)
    assert captured == ["reminder"]

    start = read_start(path=notifier._start_path)
    write_ack(
        CaretakerAck(start_id=start.start_id, acknowledged_at="2026-01-01T00:00:00+00:00"),
        path=notifier._ack_path,
    )
    await asyncio.sleep(0.05)

    clock.value = 20.0
    await asyncio.sleep(0.05)
    assert captured == ["reminder"]

    stop.set()
    await asyncio.wait_for(task, timeout=5)
    await notifier.stop()

    log = _read_log(tmp_path / "caretaker")
    assert sum(1 for r in log if r.get("transition") == "acknowledged") == 1


async def test_ack_with_wrong_id_does_not_stop_reminders(tmp_path):
    clock = FakeClock(0.0)
    captured = []
    notifier = _notifier(
        tmp_path, _valid_config(reminder_interval_s=10.0), _make_notify(captured), clock
    )
    await notifier.start()
    stop = asyncio.Event()
    task = asyncio.create_task(notifier.run(stop))

    clock.value = 10.0
    await asyncio.sleep(0.05)
    assert captured == ["reminder"]

    write_ack(
        CaretakerAck(start_id="0" * 32, acknowledged_at="2026-01-01T00:00:00+00:00"),
        path=notifier._ack_path,
    )
    await asyncio.sleep(0.05)

    clock.value = 20.0
    await asyncio.sleep(0.05)
    assert captured == ["reminder", "reminder"]

    stop.set()
    await asyncio.wait_for(task, timeout=5)
    await notifier.stop()


async def test_send_event_swallows_raising_notify_fn(tmp_path):
    clock = FakeClock(0.0)

    def raising_notify(config, notice, *, secrets_path=None):
        raise RuntimeError("notify failed")

    notifier = _notifier(tmp_path, _valid_config(), raising_notify, clock)
    await notifier.start()
    results = await notifier.send_event("spot_escalation")
    assert results == []
    await notifier.stop()


def test_send_event_best_effort_no_channels_does_not_call_notify():
    calls = []

    def notify_fn(config, notice, *, secrets_path=None):
        calls.append(notice)

    send_event_best_effort({"channels": []}, "boot_failed", notify_fn=notify_fn)
    assert calls == []


def test_send_event_best_effort_raising_notify_fn_does_not_propagate():
    def raising_notify(config, notice, *, secrets_path=None):
        raise RuntimeError("notify failed")

    send_event_best_effort(
        {"channels": [{"kind": "desktop"}]},
        "boot_failed",
        notify_fn=raising_notify,
    )
