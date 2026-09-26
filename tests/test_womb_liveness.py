# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the womb liveness interface."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.lifecycle.womb_liveness import (
    WOMB_PRESENCE_TYPE,
    WOMB_SOURCE,
    WombLiveness,
    check_womb_liveness,
)
from kaine.preboot import CheckResult


@pytest.mark.asyncio
async def test_local_womb_live_when_probe_passes():
    async def fake_check(config):
        return [
            CheckResult("perception", "video probe", "PASS", ""),
            CheckResult("perception", "audio probe", "PASS", ""),
        ]

    config = {
        "modules": {"topos": True, "audition": True},
        "perception_feed": {"mode": "womb"},
    }
    result = await check_womb_liveness(config, None, perception_check=fake_check)
    assert result == WombLiveness(True, "local", "")


@pytest.mark.asyncio
async def test_local_womb_not_live_when_audio_fails():
    async def fake_check(config):
        return [
            CheckResult("perception", "video probe", "PASS", ""),
            CheckResult("perception", "audio probe", "FAIL", "muted"),
        ]

    config = {
        "modules": {"topos": True, "audition": True},
        "perception_feed": {"mode": "womb"},
    }
    result = await check_womb_liveness(config, None, perception_check=fake_check)
    assert not result.live
    assert result.provider == "local"
    assert "muted" in result.reason


@pytest.mark.asyncio
async def test_local_womb_not_live_when_probe_raises():
    async def fake_check(config):
        raise RuntimeError("synthesis failed")

    config = {
        "modules": {"topos": True, "audition": True},
        "perception_feed": {"mode": "womb"},
    }
    result = await check_womb_liveness(config, None, perception_check=fake_check)
    assert not result.live
    assert "RuntimeError: synthesis failed" in result.reason


@pytest.mark.asyncio
async def test_local_womb_not_live_when_audition_disabled():
    async def fake_check(config):
        return [CheckResult("perception", "video probe", "PASS", "")]

    config = {
        "modules": {"topos": True, "audition": False},
        "perception_feed": {"mode": "womb"},
    }
    result = await check_womb_liveness(config, None, perception_check=fake_check)
    assert not result.live
    assert "[modules].audition" in result.reason


@pytest.mark.asyncio
async def test_local_womb_not_live_when_probe_returns_no_rows():
    async def fake_check(config):
        return []

    config = {
        "modules": {"topos": True, "audition": True},
        "perception_feed": {"mode": "womb"},
    }
    result = await check_womb_liveness(config, None, perception_check=fake_check)
    assert not result.live
    assert "configuration alone is not a womb" in result.reason


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
async def test_external_womb_live_when_presence_in_window(bus):
    await bus.publish(
        Event(
            timestamp=datetime.now(timezone.utc),
            source=WOMB_SOURCE,
            type=WOMB_PRESENCE_TYPE,
            payload={"provider": "external", "frame_index": 1},
            salience=0.1,
        )
    )
    result = await check_womb_liveness({"perception_feed": {"mode": "external"}}, bus)
    assert result == WombLiveness(True, "external", "")


@pytest.mark.asyncio
async def test_external_womb_not_live_when_presence_outside_window(bus):
    await bus.publish(
        Event(
            timestamp=datetime.now(timezone.utc),
            source=WOMB_SOURCE,
            type=WOMB_PRESENCE_TYPE,
            payload={"provider": "external", "frame_index": 1},
            salience=0.1,
        )
    )
    await asyncio.sleep(0.05)
    result = await check_womb_liveness(
        {"perception_feed": {"mode": "external"}},
        bus,
        window_s=0.01,
    )
    assert not result.live
    assert f"no {WOMB_PRESENCE_TYPE} presence event" in result.reason


@pytest.mark.asyncio
async def test_external_womb_live_despite_later_readiness_event(bus):
    await bus.publish(
        Event(
            timestamp=datetime.now(timezone.utc),
            source=WOMB_SOURCE,
            type=WOMB_PRESENCE_TYPE,
            payload={"provider": "external", "frame_index": 1},
            salience=0.1,
        )
    )
    await bus.publish(
        Event(
            timestamp=datetime.now(timezone.utc),
            source=WOMB_SOURCE,
            type="gestation.readiness",
            payload={"ready": True},
            salience=0.1,
        )
    )
    result = await check_womb_liveness({"perception_feed": {"mode": "external"}}, bus)
    assert result.live


@pytest.mark.asyncio
async def test_external_womb_not_live_without_bus():
    result = await check_womb_liveness({"perception_feed": {"mode": "external"}}, None)
    assert not result.live
    assert "no bus" in result.reason


@pytest.mark.asyncio
async def test_external_womb_not_live_when_bus_raises():
    class BadBus:
        async def server_time_ms(self):
            raise RuntimeError("redis down")

        async def range(self, *args, **kwargs):
            return []

    result = await check_womb_liveness(
        {"perception_feed": {"mode": "external"}}, BadBus()
    )
    assert not result.live
    assert "RuntimeError: redis down" in result.reason


@pytest.mark.parametrize("window_s", [0.0, -1.0, float("nan")])
@pytest.mark.asyncio
async def test_check_womb_liveness_rejects_bad_window(window_s):
    with pytest.raises(ValueError):
        await check_womb_liveness(
            {"perception_feed": {"mode": "external"}}, None, window_s=window_s
        )
