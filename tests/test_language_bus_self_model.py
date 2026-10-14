# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The language module seeds its persona from the *bus-mediated* self-model snapshot,
not an in-process self-model reference (``distributed-deployment`` task 2.2 / 5.1).

This is the decoupling that lets the language organ run in a separate process /
on a separate trusted host from the self-model module: the two coordinate over the shared
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
from kaine.modules.language import FakeChatClient, IntentExpressionLog, Language


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _publish_self_model(bus: AsyncBus, **fields) -> None:
    # Source "self_model" routes to the self_model.out stream the language module consumes.
    await bus.publish(
        Event(
            source="self_model",
            type="self_model.document",
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


def _make_language(bus: AsyncBus, tmp_path: Path) -> Language:
    return Language(
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
async def test_language_boots_against_bus_mediated_self_model(bus: AsyncBus, tmp_path: Path):
    # A self-model snapshot already on the bus at boot (the self-model module's initial
    # publish) seeds the language module's persona — no in-process provider is wired.
    await _publish_self_model(bus, name="Kaine Umarov")
    language = _make_language(bus, tmp_path)
    assert language._self_model_provider is None  # no in-process reference
    await language.initialize()
    try:
        ok = await _wait_for(lambda: language._bus_self_model is not None)
        assert ok
        model = language._self_model()
        assert model["name"] == "Kaine Umarov"
        assert "curiosity" in model["values"]
        assert model["behavioral_norms"] == ["be kind"]
    finally:
        await language.shutdown()


@pytest.mark.asyncio
async def test_language_picks_up_snapshot_published_after_boot(bus: AsyncBus, tmp_path: Path):
    language = _make_language(bus, tmp_path)
    await language.initialize()
    try:
        # Nothing yet → minimal persona.
        assert language._self_model() == {}
        await _publish_self_model(bus, name="Kaine Later")
        ok = await _wait_for(lambda: language._bus_self_model is not None)
        assert ok
        assert language._self_model()["name"] == "Kaine Later"
    finally:
        await language.shutdown()


@pytest.mark.asyncio
async def test_bus_snapshot_overrides_in_process_provider(bus: AsyncBus, tmp_path: Path):
    # If a legacy provider is injected, a bus snapshot still wins (the bus is the
    # canonical, split-host-safe source).
    language = _make_language(bus, tmp_path)
    language.set_self_model_provider(lambda: {"name": "Legacy", "values": []})
    assert language._self_model()["name"] == "Legacy"
    await language.initialize()
    try:
        await _publish_self_model(bus, name="Kaine Bus")
        ok = await _wait_for(
            lambda: (language._bus_self_model or {}).get("name") == "Kaine Bus"
        )
        assert ok
        assert language._self_model()["name"] == "Kaine Bus"
    finally:
        await language.shutdown()
