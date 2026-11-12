# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import time

import pytest

from kaine.residency.ledger import Ledger, State


@pytest.mark.asyncio
async def test_register_and_headroom():
    ledger = Ledger(budget_bytes=1000)
    ledger.register("stt", footprint_bytes=400)
    assert ledger.headroom == 1000
    assert ledger.reserved == 0
    assert ledger.get("stt").state == State.ABSENT

@pytest.mark.asyncio
async def test_admit_reserves_headroom():
    ledger = Ledger(budget_bytes=1000)
    ledger.register("stt")
    ok = await ledger.try_admit("stt", 400)
    assert ok is True
    assert ledger.get("stt").state == State.LOADING
    assert ledger.headroom == 600
    assert ledger.reserved == 400

@pytest.mark.asyncio
async def test_admit_insufficient_headroom():
    ledger = Ledger(budget_bytes=500)
    ledger.register("stt")
    ledger.register("tts")
    await ledger.try_admit("stt", 400)
    ok = await ledger.try_admit("tts", 200)
    assert ok is False

@pytest.mark.asyncio
async def test_admit_unregistered_returns_false():
    ledger = Ledger(budget_bytes=1000)
    ok = await ledger.try_admit("unknown", 100)
    assert ok is False

@pytest.mark.asyncio
async def test_admit_already_resident_is_idempotent():
    ledger = Ledger(budget_bytes=1000)
    ledger.register("stt")
    await ledger.try_admit("stt", 400)
    ledger.mark_resident("stt")
    ok = await ledger.try_admit("stt", 400)
    assert ok is True
    assert ledger.reserved == 400

@pytest.mark.asyncio
async def test_mark_resident():
    ledger = Ledger(budget_bytes=1000)
    ledger.register("stt")
    await ledger.try_admit("stt", 400)
    ledger.mark_resident("stt")
    assert ledger.get("stt").state == State.RESIDENT

@pytest.mark.asyncio
async def test_mark_cold_releases_footprint():
    ledger = Ledger(budget_bytes=1000)
    ledger.register("stt")
    await ledger.try_admit("stt", 400)
    ledger.mark_resident("stt")
    ledger.mark_unloading("stt")
    ledger.mark_cold("stt")
    assert ledger.get("stt").state == State.COLD
    assert ledger.headroom == 1000
    assert ledger.reserved == 0

@pytest.mark.asyncio
async def test_eviction_candidates_order(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    ledger = Ledger(budget_bytes=10000, pin="organ")
    ledger.register("stt", ttl_seconds=60)
    ledger.register("tts", ttl_seconds=60)
    ledger.register("organ", ttl_seconds=120)
    await ledger.try_admit("stt", 200)
    ledger.mark_resident("stt")
    now = 1001.0
    await ledger.try_admit("tts", 300)
    ledger.mark_resident("tts")
    now = 1002.0
    await ledger.try_admit("organ", 500)
    ledger.mark_resident("organ")
    now = 1100.0
    candidates = ledger.eviction_candidates(400)
    assert "organ" not in candidates
    assert candidates[0] == "stt"

@pytest.mark.asyncio
async def test_eviction_skips_inflight():
    ledger = Ledger(budget_bytes=1000, pin="none")
    ledger.register("stt")
    await ledger.try_admit("stt", 400)
    ledger.mark_resident("stt")
    ledger.increment_inflight("stt")
    candidates = ledger.eviction_candidates(400)
    assert candidates == []

@pytest.mark.asyncio
async def test_ttl_expired(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    ledger = Ledger(budget_bytes=10000, pin="organ")
    ledger.register("stt", ttl_seconds=60)
    ledger.register("organ", ttl_seconds=120)
    await ledger.try_admit("stt", 200)
    ledger.mark_resident("stt")
    await ledger.try_admit("organ", 500)
    ledger.mark_resident("organ")
    now = 1070.0
    expired = ledger.ttl_expired()
    assert "stt" in expired
    assert "organ" not in expired

@pytest.mark.asyncio
async def test_pin_sets_entry_pinned():
    ledger = Ledger(budget_bytes=1000, pin="organ")
    ledger.register("organ")
    assert ledger.get("organ").pinned is True
    ledger.register("stt")
    assert ledger.get("stt").pinned is False

def test_decrement_inflight_floor():
    ledger = Ledger(budget_bytes=1000)
    ledger.register("stt")
    ledger.decrement_inflight("stt")
    assert ledger.get("stt").inflight == 0

@pytest.mark.asyncio
async def test_record_use_updates_last_used(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    ledger = Ledger(budget_bytes=1000)
    ledger.register("stt")
    await ledger.try_admit("stt", 200)
    ledger.mark_resident("stt")
    now = 2000.0
    ledger.record_use("stt")
    assert ledger.get("stt").last_used == 2000.0
