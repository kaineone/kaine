# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import logging
import struct

import pytest

from kaine.modules.audition.live import LiveMicConfig, LiveMicrophone


@pytest.mark.asyncio
async def test_chunk_flush_is_not_logged_at_info(caplog):
    caplog.set_level(logging.INFO, logger="kaine.modules.audition.live")
    calls = []

    async def sink(*args, **kwargs):
        calls.append((args, kwargs))

    t = [0.0]
    mic = LiveMicrophone(
        sink,
        config=LiveMicConfig(summary_interval_s=10.0),
        clock=lambda: t[0],
    )
    frame = struct.pack("<480h", *([0] * 480))
    for _ in range(5):
        await mic._flush_utterance([frame], min_frames=1)
    info_records = [
        r for r in caplog.records if r.levelno >= logging.INFO and "utterance_ended" in r.message
    ]
    assert not info_records
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_summary_logged_once_per_interval(caplog):
    caplog.set_level(logging.INFO, logger="kaine.modules.audition.live")
    calls = []

    async def sink(*args, **kwargs):
        calls.append((args, kwargs))

    t = [0.0]
    mic = LiveMicrophone(
        sink,
        config=LiveMicConfig(summary_interval_s=10.0),
        clock=lambda: t[0],
    )
    frame = struct.pack("<480h", *([0] * 480))

    def flush_at(new_time):
        t[0] = new_time
        return mic._flush_utterance([frame], min_frames=1)

    await flush_at(0.0)
    await flush_at(1.0)
    await flush_at(2.0)
    await flush_at(3.0)
    summary_before = [
        r for r in caplog.records if r.levelno == logging.INFO and "live mic:" in r.message
    ]
    assert len(summary_before) == 0

    await flush_at(10.5)
    summary_records = [
        r for r in caplog.records if r.levelno == logging.INFO and "live mic:" in r.message
    ]
    assert len(summary_records) == 1
    assert "live mic: 5 chunks (4800 pcm bytes)" in summary_records[0].message

    caplog.clear()
    await flush_at(12.0)
    summary_after = [
        r for r in caplog.records if r.levelno == logging.INFO and "live mic:" in r.message
    ]
    assert len(summary_after) == 0


@pytest.mark.asyncio
async def test_below_min_counted_in_summary(caplog):
    caplog.set_level(logging.INFO, logger="kaine.modules.audition.live")
    calls = []

    async def sink(*args, **kwargs):
        calls.append((args, kwargs))

    t = [0.0]
    mic = LiveMicrophone(
        sink,
        config=LiveMicConfig(summary_interval_s=10.0),
        clock=lambda: t[0],
    )
    frame = struct.pack("<480h", *([0] * 480))

    t[0] = 0.0
    await mic._flush_utterance([frame], min_frames=2)
    assert len(calls) == 0
    t[0] = 10.5
    await mic._flush_utterance([frame], min_frames=1)
    summary_records = [
        r for r in caplog.records if r.levelno == logging.INFO and "live mic:" in r.message
    ]
    assert len(summary_records) == 1
    assert "1 below minimum" in summary_records[0].message


def test_default_summary_interval_is_five_minutes():
    assert LiveMicConfig().summary_interval_s == 300.0
