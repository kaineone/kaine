# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import time
from types import SimpleNamespace

import pytest
import redis.asyncio as aioredis

from kaine import legacy_aliases, legacy_names
from kaine.bus import legacy_streams
from kaine.bus.legacy_streams import OldStream
from kaine.preboot import PASS, SKIP, WARN, _probe_old_streams, check_old_streams


@pytest.fixture
def keys_done(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")


@pytest.mark.asyncio
async def test_check_old_streams_warns_when_deletable_exist(keys_done):
    now_ms = int(time.time() * 1000)

    async def probe():
        return [
            OldStream(
                old=legacy_aliases.old_stream_name("sleep.out"),
                new="sleep.out",
                present=True,
                is_stream=True,
                length=3,
                memory_bytes=42,
                last_entry_ms=now_ms - 20 * 60 * 1000,
            )
        ], now_ms

    results = await check_old_streams({}, probe=probe)
    assert len(results) == 1
    assert results[0].status == WARN
    assert results[0].name == "Old stream names"
    assert "python -m kaine.bus.legacy_streams --delete" in results[0].detail


@pytest.mark.asyncio
async def test_check_old_streams_passes_when_empty(keys_done):
    async def probe():
        return [], int(time.time() * 1000)

    results = await check_old_streams({}, probe=probe)
    assert results[0].status == PASS
    assert results[0].detail == "no old-named streams remain"


@pytest.mark.asyncio
async def test_check_old_streams_warns_on_probe_error(keys_done):
    async def probe():
        raise RuntimeError("boom")

    results = await check_old_streams({}, probe=probe)
    assert results[0].status == WARN
    assert results[0].detail == "could not check for old-named streams (RuntimeError)"


@pytest.mark.asyncio
async def test_check_old_streams_skips_when_keys_pending(monkeypatch):
    monkeypatch.setattr(legacy_names, "SCOPE_STATUS", {})

    async def probe():
        return [], int(time.time() * 1000)

    results = await check_old_streams({}, probe=probe)
    assert results[0].status == SKIP
    assert results[0].detail == "the keys rename has not run"


@pytest.mark.asyncio
async def test_check_old_streams_uses_the_probe_clock(keys_done):
    local_now_ms = int(time.time() * 1000)
    now_ms = local_now_ms - 60 * 60 * 1000

    async def probe():
        return [
            OldStream(
                old=legacy_aliases.old_stream_name("sleep.out"),
                new="sleep.out",
                present=True,
                is_stream=True,
                length=3,
                memory_bytes=42,
                last_entry_ms=now_ms - 5 * 60 * 1000,
            )
        ], now_ms

    results = await check_old_streams({}, probe=probe)
    assert len(results) == 1
    assert results[0].status == PASS
    assert results[0].detail == "no old-named streams remain"


@pytest.mark.asyncio
async def test_probe_treats_an_unreadable_newest_entry_as_recent(keys_done, monkeypatch):
    sleep_old = legacy_aliases.old_stream_name("sleep.out")

    class FakeClient:
        async def exists(self, name):
            return 1 if name == sleep_old else 0

        async def type(self, name):
            return "stream" if name == sleep_old else b"none"

        async def xlen(self, name):
            return 2 if name == sleep_old else 0

        async def memory_usage(self, name):
            return 100

        async def xrevrange(self, name, count=1):
            raise RuntimeError("cannot read")

        async def time(self):
            return (1_700_000_000, 250_000)

        async def close(self):
            pass

    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: FakeClient())
    monkeypatch.setattr(
        "kaine.bus.config.load_bus_config", lambda: SimpleNamespace(url="redis://unused")
    )

    entries, now_ms = await _probe_old_streams()
    assert now_ms == 1_700_000_000_250
    sleep_entry = next(e for e in entries if e.old == sleep_old)
    assert sleep_entry.last_entry_ms == now_ms
    assert sleep_entry not in legacy_streams.deletable(entries, now_ms=now_ms)
