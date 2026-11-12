# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Integration tests for KAINE residency on a small unified host."""

import pytest

from kaine.residency.events import (
    clear_residency_events,
    residency_events,
)
from kaine.residency.ledger import Ledger, State
from kaine.residency.router import ResidencyRouter

MIB = 1 << 20
GIB = 1 << 30


@pytest.mark.asyncio
async def test_voice_turn_completes_under_budget():
    budget = 8 * GIB
    ledger = Ledger(budget_bytes=budget)
    router = ResidencyRouter(ledger)
    router.register("stt", footprint_bytes=400 * MIB)
    router.register("language", footprint_bytes=3 * GIB)
    router.register("tts", footprint_bytes=350 * MIB)

    clear_residency_events()
    peak_reserved = 0

    admitted = await router.before_load("stt", 400 * MIB)
    assert admitted is True
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.after_load("stt")
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.record_use("stt")
    assert ledger.get("stt").state == State.RESIDENT
    assert ledger.headroom >= 0
    peak_reserved = max(peak_reserved, ledger.reserved)

    router.before_unload("stt")
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.after_unload("stt")
    peak_reserved = max(peak_reserved, ledger.reserved)

    admitted = await router.before_load("language", 3 * GIB)
    assert admitted is True
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.after_load("language")
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.record_use("language")
    assert ledger.get("language").state == State.RESIDENT
    assert ledger.headroom >= 0
    peak_reserved = max(peak_reserved, ledger.reserved)

    admitted = await router.before_load("tts", 350 * MIB)
    assert admitted is True
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.after_load("tts")
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.record_use("tts")
    assert ledger.get("tts").state == State.RESIDENT
    assert ledger.headroom >= 0
    peak_reserved = max(peak_reserved, ledger.reserved)

    router.before_unload("tts")
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.after_unload("tts")
    peak_reserved = max(peak_reserved, ledger.reserved)

    assert ledger.get("language").state == State.RESIDENT
    assert all(entry.state != State.ABSENT for entry in ledger.entries().values())
    assert peak_reserved <= budget


@pytest.mark.asyncio
async def test_voice_turn_events_fire():
    budget = 8 * GIB
    ledger = Ledger(budget_bytes=budget)
    router = ResidencyRouter(ledger)
    router.register("stt", footprint_bytes=400 * MIB)
    router.register("language", footprint_bytes=3 * GIB)
    router.register("tts", footprint_bytes=350 * MIB)

    clear_residency_events()

    await router.before_load("stt", 400 * MIB)
    router.after_load("stt")
    router.record_use("stt")
    router.before_unload("stt")
    router.after_unload("stt")

    await router.before_load("language", 3 * GIB)
    router.after_load("language")
    router.record_use("language")

    await router.before_load("tts", 350 * MIB)
    router.after_load("tts")
    router.record_use("tts")
    router.before_unload("tts")
    router.after_unload("tts")

    events = residency_events()

    assert sum(event.kind == "load_start" and event.name == "stt" for event in events) == 1
    assert sum(event.kind == "load_start" and event.name == "language" for event in events) == 1
    assert sum(event.kind == "load_start" and event.name == "tts" for event in events) == 1

    assert sum(event.kind == "load_end" and event.name == "stt" for event in events) == 1
    assert sum(event.kind == "load_end" and event.name == "language" for event in events) == 1
    assert sum(event.kind == "load_end" and event.name == "tts" for event in events) == 1

    assert sum(event.kind == "unload" and event.name == "stt" for event in events) == 1
    assert sum(event.kind == "unload" and event.name == "tts" for event in events) == 1

    assert not any(event.kind in {"evict", "queue_drop"} for event in events)
    assert all(event.ts > 0 for event in events)


@pytest.mark.asyncio
async def test_no_module_disabled_at_8gib():
    budget = 8 * GIB
    ledger = Ledger(budget_bytes=budget)
    router = ResidencyRouter(ledger)
    router.register("stt", footprint_bytes=400 * MIB)
    router.register("language", footprint_bytes=3 * GIB)
    router.register("tts", footprint_bytes=350 * MIB)

    assert await router.before_load("stt", 400 * MIB) is True
    router.after_load("stt")
    router.record_use("stt")
    router.before_unload("stt")
    router.after_unload("stt")

    assert await router.before_load("language", 3 * GIB) is True
    router.after_load("language")
    router.record_use("language")

    assert await router.before_load("tts", 350 * MIB) is True
    router.after_load("tts")
    router.record_use("tts")
    router.before_unload("tts")
    router.after_unload("tts")

    assert ledger.get("stt").state == State.COLD
    assert ledger.get("language").state == State.RESIDENT
    assert ledger.get("tts").state == State.COLD


@pytest.mark.asyncio
async def test_budget_exhaustion_refuses_admission():
    budget = 4 * GIB
    ledger = Ledger(budget_bytes=budget)
    router = ResidencyRouter(ledger)
    router.register("stt", footprint_bytes=400 * MIB)
    router.register("language", footprint_bytes=3 * GIB)
    router.register("tts", footprint_bytes=350 * MIB)

    assert await router.before_load("language", 3 * GIB) is True
    router.after_load("language")

    assert await router.before_load("stt", 400 * MIB) is True
    router.after_load("stt")

    assert await router.before_load("tts", 350 * MIB) is True
    router.after_load("tts")

    router.register("vision", footprint_bytes=2 * GIB)
    assert await router.before_load("vision", 2 * GIB) is False
    assert ledger.get("vision").state == State.ABSENT


@pytest.mark.asyncio
async def test_sequential_multiplexing_within_budget():
    budget = 2 * GIB
    ledger = Ledger(budget_bytes=budget)
    router = ResidencyRouter(ledger)
    router.register("stt", footprint_bytes=800 * MIB)
    router.register("language", footprint_bytes=1536 * MIB)
    router.register("tts", footprint_bytes=600 * MIB)

    peak_reserved = 0

    stt_loaded = await router.before_load("stt", 800 * MIB)
    assert stt_loaded is True
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.after_load("stt")
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.record_use("stt")
    router.before_unload("stt")
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.after_unload("stt")
    peak_reserved = max(peak_reserved, ledger.reserved)

    language_loaded = await router.before_load("language", 1536 * MIB)
    assert language_loaded is True
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.after_load("language")
    peak_reserved = max(peak_reserved, ledger.reserved)

    tts_loaded_before_unload = await router.before_load("tts", 600 * MIB)
    assert tts_loaded_before_unload is False

    router.before_unload("language")
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.after_unload("language")
    peak_reserved = max(peak_reserved, ledger.reserved)

    tts_loaded_after_unload = await router.before_load("tts", 600 * MIB)
    assert tts_loaded_after_unload is True
    peak_reserved = max(peak_reserved, ledger.reserved)
    router.after_load("tts")
    peak_reserved = max(peak_reserved, ledger.reserved)

    assert stt_loaded
    assert language_loaded
    assert tts_loaded_after_unload
    assert peak_reserved <= budget
