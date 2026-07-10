# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Lingua seeds its persona from the *bus-mediated* Eidolon self-model snapshot,
not an in-process Eidolon reference (``distributed-deployment`` task 2.2 / 5.1).

This is the decoupling that lets the language organ run in a separate process /
on a separate trusted host from Eidolon: the two coordinate over the shared
authenticated bus, never through a boot-time Python object handle.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.lingua import FakeChatClient, IntentExpressionLog, Lingua


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _publish_self_model(bus: AsyncBus, **fields) -> None:
    # Source "eidolon" routes to the eidolon.out stream Lingua consumes.
    await bus.publish(
        Event(
            source="eidolon",
            type="eidolon.self_model",
            payload={
                "name": fields.get("name", "Kaine Umarov"),
                "values": fields.get("values", ["curiosity", "honesty"]),
                "behavioral_norms": fields.get("behavioral_norms", ["be kind"]),
                "personality_baseline": fields.get(
                    "personality_baseline", {"openness": 0.8}
                ),
            },
            salience=0.4,
            timestamp=datetime.now(timezone.utc),
        )
    )


def _make_lingua(bus: AsyncBus, tmp_path: Path) -> Lingua:
    return Lingua(
        bus,
        chat_client=FakeChatClient(),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )


async def _wait_for(pred, *, timeout_s: float = 2.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.02)
    return pred()


@pytest.mark.asyncio
async def test_lingua_boots_against_bus_mediated_self_model(bus: AsyncBus, tmp_path: Path):
    # A self-model snapshot already on the bus at boot (the Eidolon initial
    # publish) seeds Lingua's persona — no in-process provider is wired.
    await _publish_self_model(bus, name="Kaine Umarov")
    lingua = _make_lingua(bus, tmp_path)
    assert lingua._self_model_provider is None  # no in-process reference
    await lingua.initialize()
    try:
        ok = await _wait_for(lambda: lingua._bus_self_model is not None)
        assert ok
        model = lingua._self_model()
        assert model["name"] == "Kaine Umarov"
        assert "curiosity" in model["values"]
        assert model["behavioral_norms"] == ["be kind"]
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_lingua_picks_up_snapshot_published_after_boot(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path)
    await lingua.initialize()
    try:
        # Nothing yet → minimal persona.
        assert lingua._self_model() == {}
        await _publish_self_model(bus, name="Kaine Later")
        ok = await _wait_for(lambda: lingua._bus_self_model is not None)
        assert ok
        assert lingua._self_model()["name"] == "Kaine Later"
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_bus_snapshot_overrides_in_process_provider(bus: AsyncBus, tmp_path: Path):
    # If a legacy provider is injected, a bus snapshot still wins (the bus is the
    # canonical, split-host-safe source).
    lingua = _make_lingua(bus, tmp_path)
    lingua.set_self_model_provider(lambda: {"name": "Legacy", "values": []})
    assert lingua._self_model()["name"] == "Legacy"
    await lingua.initialize()
    try:
        await _publish_self_model(bus, name="Kaine Bus")
        ok = await _wait_for(
            lambda: (lingua._bus_self_model or {}).get("name") == "Kaine Bus"
        )
        assert ok
        assert lingua._self_model()["name"] == "Kaine Bus"
    finally:
        await lingua.shutdown()
