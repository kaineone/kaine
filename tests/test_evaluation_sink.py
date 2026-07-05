# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from kaine.evaluation.sink import AsyncJsonlSink, _utc_date_str


@pytest.mark.asyncio
async def test_sink_writes_jsonl(tmp_path):
    sink = AsyncJsonlSink(tmp_path, name="probe", flush_interval_s=0.05)
    await sink.start()
    try:
        await sink.write({"a": 1})
        await sink.write({"b": 2})
        await asyncio.sleep(0.2)
        files = list(tmp_path.glob("probe-*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"a": 1}
        assert json.loads(lines[1]) == {"b": 2}
        assert sink.wrote_count == 2
    finally:
        await sink.stop()


@pytest.mark.asyncio
async def test_sink_final_flush_on_stop(tmp_path):
    sink = AsyncJsonlSink(tmp_path, name="probe", flush_interval_s=10.0)
    await sink.start()
    await sink.write({"x": 1})
    await sink.stop()
    files = list(tmp_path.glob("probe-*.jsonl"))
    assert len(files) == 1
    assert files[0].read_text().strip() == json.dumps({"x": 1})


@pytest.mark.asyncio
async def test_sink_full_queue_drops_oldest(tmp_path):
    sink = AsyncJsonlSink(tmp_path, name="probe", queue_maxsize=2, flush_interval_s=10.0)
    # No start: queue is fed sync via write() returning immediately.
    await sink.write({"i": 1})
    await sink.write({"i": 2})
    await sink.write({"i": 3})  # should drop the oldest, push newest
    assert sink._queue.qsize() == 2
    assert sink.dropped_count >= 1


def test_sink_retention_purges_old_files(tmp_path):
    today_path = tmp_path / f"probe-{_utc_date_str()}.jsonl"
    today_path.write_text("{}\n")
    old_path = tmp_path / "probe-1970-01-01.jsonl"
    old_path.write_text("{}\n")
    # Make the old file's mtime ancient.
    ancient = time.time() - 60 * 86400
    import os
    os.utime(old_path, (ancient, ancient))
    sink = AsyncJsonlSink(tmp_path, name="probe", retention_days=30)
    sink._enforce_retention()
    assert today_path.exists()
    assert not old_path.exists()


def test_sink_retention_zero_disabled(tmp_path):
    old = tmp_path / "probe-2020-01-01.jsonl"
    old.write_text("{}\n")
    ancient = time.time() - 1000 * 86400
    import os
    os.utime(old, (ancient, ancient))
    sink = AsyncJsonlSink(tmp_path, name="probe", retention_days=0)
    sink._enforce_retention()
    assert old.exists()
