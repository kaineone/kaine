# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import time

import pytest

from kaine.residency.events import clear_residency_events, residency_events
from kaine.residency.ledger import Ledger, State
from kaine.residency.router import ResidencyRouter


@pytest.mark.asyncio
async def test_register_delegates_to_ledger():
    ledger = Ledger(budget_bytes=10_000)
    router = ResidencyRouter(ledger)
    router.register("face_detector", footprint_bytes=500, ttl_seconds=60)
    entry = ledger.get("face_detector")
    assert entry is not None
    assert entry.footprint_bytes == 500
    assert entry.ttl_seconds == 60
    assert entry.state == State.ABSENT


@pytest.mark.asyncio
async def test_load_lifecycle():
    clear_residency_events()
    ledger = Ledger(budget_bytes=10_000)
    router = ResidencyRouter(ledger)
    router.register("stt", footprint_bytes=400)

    admitted = await router.before_load("stt", footprint_bytes=400)
    assert admitted is True
    assert ledger.get("stt").state == State.LOADING

    router.after_load("stt")
    assert ledger.get("stt").state == State.RESIDENT

    events = residency_events()
    kinds = [e.kind for e in events]
    assert "load_start" in kinds
    assert "load_end" in kinds
    load_end = [e for e in events if e.kind == "load_end"][0]
    assert load_end.duration_seconds >= 0.0


@pytest.mark.asyncio
async def test_unload_lifecycle():
    clear_residency_events()
    ledger = Ledger(budget_bytes=10_000)
    router = ResidencyRouter(ledger)
    router.register("stt", footprint_bytes=400)
    await router.before_load("stt", footprint_bytes=400)
    router.after_load("stt")
    clear_residency_events()

    router.before_unload("stt")
    assert ledger.get("stt").state == State.UNLOADING

    router.after_unload("stt")
    assert ledger.get("stt").state == State.COLD

    events = residency_events()
    assert any(e.kind == "unload" and e.reason == "explicit" for e in events)


@pytest.mark.asyncio
async def test_before_load_insufficient_budget():
    ledger = Ledger(budget_bytes=500)
    router = ResidencyRouter(ledger)
    router.register("big_model", footprint_bytes=600)

    admitted = await router.before_load("big_model", footprint_bytes=600)
    assert admitted is False
    assert ledger.get("big_model").state != State.LOADING


@pytest.mark.asyncio
async def test_record_use_updates_last_used():
    ledger = Ledger(budget_bytes=10_000)
    router = ResidencyRouter(ledger)
    router.register("stt", footprint_bytes=400)
    await router.before_load("stt", footprint_bytes=400)
    router.after_load("stt")

    before = ledger.get("stt").last_used
    time.sleep(0.01)
    router.record_use("stt")
    after = ledger.get("stt").last_used
    assert after > before


@pytest.mark.asyncio
async def test_ledger_property():
    ledger = Ledger(budget_bytes=10_000)
    router = ResidencyRouter(ledger)
    assert router.ledger is ledger


@pytest.mark.asyncio
async def test_before_load_unregistered_returns_false():
    ledger = Ledger(budget_bytes=10_000)
    router = ResidencyRouter(ledger)
    admitted = await router.before_load("unknown", footprint_bytes=100)
    assert admitted is False
