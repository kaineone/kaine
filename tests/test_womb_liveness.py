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
    check_womb_live,
    check_womb_ready,
)
from kaine.preboot import CheckResult


@pytest.fixture(autouse=True)
def _oscillator_extra_present(monkeypatch):
    # The local-womb readiness also requires the oscillator extra; these tests
    # are about the perception probe, so pin its availability rather than
    # depending on whether the test host has snnTorch.
    monkeypatch.setattr("kaine.oscillator.snntorch_available", lambda: True)


@pytest.mark.asyncio
async def test_ready_local_womb_live_when_probe_passes():
    async def fake_check(config):
        return [
            CheckResult("perception", "video probe", "PASS", ""),
            CheckResult("perception", "audio probe", "PASS", ""),
        ]

    config = {
        "modules": {"topos": True, "audition": True, "soma": True},
        "soma": {"self_rhythm_enabled": True},
        "perception_feed": {"mode": "womb"},
    }
    result = await check_womb_ready(config, None, perception_check=fake_check)
    assert result == WombLiveness(True, "local", "")


@pytest.mark.asyncio
async def test_ready_local_womb_not_live_when_audio_fails():
    async def fake_check(config):
        return [
            CheckResult("perception", "video probe", "PASS", ""),
            CheckResult("perception", "audio probe", "FAIL", "muted"),
        ]

    config = {
        "modules": {"topos": True, "audition": True, "soma": True},
        "soma": {"self_rhythm_enabled": True},
        "perception_feed": {"mode": "womb"},
    }
    result = await check_womb_ready(config, None, perception_check=fake_check)
    assert not result.live
    assert result.provider == "local"
    assert "muted" in result.reason


@pytest.mark.asyncio
async def test_ready_local_womb_not_live_when_probe_raises():
    async def fake_check(config):
        raise RuntimeError("synthesis failed")

    config = {
        "modules": {"topos": True, "audition": True, "soma": True},
        "soma": {"self_rhythm_enabled": True},
        "perception_feed": {"mode": "womb"},
    }
    result = await check_womb_ready(config, None, perception_check=fake_check)
    assert not result.live
    assert "RuntimeError: synthesis failed" in result.reason


@pytest.mark.asyncio
async def test_ready_local_womb_not_live_when_audition_disabled():
    async def fake_check(config):
        return [CheckResult("perception", "video probe", "PASS", "")]

    config = {
        "modules": {"topos": True, "audition": False},
        "perception_feed": {"mode": "womb"},
    }
    result = await check_womb_ready(config, None, perception_check=fake_check)
    assert not result.live
    assert "[modules].audition" in result.reason


@pytest.mark.asyncio
async def test_ready_local_womb_not_live_when_probe_returns_no_rows():
    async def fake_check(config):
        return []

    config = {
        "modules": {"topos": True, "audition": True, "soma": True},
        "soma": {"self_rhythm_enabled": True},
        "perception_feed": {"mode": "womb"},
    }
    result = await check_womb_ready(config, None, perception_check=fake_check)
    assert not result.live
    assert "configuration alone is not a womb" in result.reason


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _presence_event(frame_index, provider="external", type_=WOMB_PRESENCE_TYPE):
    return Event(
        timestamp=datetime.now(timezone.utc),
        source=WOMB_SOURCE,
        type=type_,
        payload={"provider": provider, "frame_index": frame_index},
        salience=0.1,
    )


@pytest.mark.asyncio
async def test_ready_external_live_with_two_advancing_events(bus):
    await bus.publish(_presence_event(1, provider="external"))
    await bus.publish(_presence_event(2, provider="external"))
    result = await check_womb_ready(
        {"perception_feed": {"mode": "external"}}, bus
    )
    assert result == WombLiveness(True, "external", "")


@pytest.mark.asyncio
async def test_ready_external_not_live_with_one_event(bus):
    await bus.publish(_presence_event(1, provider="external"))
    result = await check_womb_ready(
        {"perception_feed": {"mode": "external"}}, bus
    )
    assert not result.live
    assert "only one presence event" in result.reason


@pytest.mark.asyncio
async def test_ready_external_not_live_with_two_same_frame_events(bus):
    await bus.publish(_presence_event(5, provider="external"))
    await bus.publish(_presence_event(5, provider="external"))
    result = await check_womb_ready(
        {"perception_feed": {"mode": "external"}}, bus
    )
    assert not result.live
    assert "frame_index did not advance" in result.reason


@pytest.mark.asyncio
async def test_ready_external_not_live_when_frame_index_missing(bus):
    await bus.publish(
        Event(
            timestamp=datetime.now(timezone.utc),
            source=WOMB_SOURCE,
            type=WOMB_PRESENCE_TYPE,
            payload={"provider": "external"},
            salience=0.1,
        )
    )
    await bus.publish(
        Event(
            timestamp=datetime.now(timezone.utc),
            source=WOMB_SOURCE,
            type=WOMB_PRESENCE_TYPE,
            payload={"provider": "external"},
            salience=0.1,
        )
    )
    result = await check_womb_ready(
        {"perception_feed": {"mode": "external"}}, bus
    )
    assert not result.live
    assert f"no {WOMB_PRESENCE_TYPE} presence event" in result.reason


@pytest.mark.asyncio
async def test_ready_external_not_live_when_frame_index_is_bool(bus):
    await bus.publish(
        Event(
            timestamp=datetime.now(timezone.utc),
            source=WOMB_SOURCE,
            type=WOMB_PRESENCE_TYPE,
            payload={"provider": "external", "frame_index": True},
            salience=0.1,
        )
    )
    await bus.publish(
        Event(
            timestamp=datetime.now(timezone.utc),
            source=WOMB_SOURCE,
            type=WOMB_PRESENCE_TYPE,
            payload={"provider": "external", "frame_index": True},
            salience=0.1,
        )
    )
    result = await check_womb_ready(
        {"perception_feed": {"mode": "external"}}, bus
    )
    assert not result.live
    assert f"no {WOMB_PRESENCE_TYPE} presence event" in result.reason


@pytest.mark.asyncio
async def test_ready_external_not_live_with_wrong_provider(bus):
    await bus.publish(_presence_event(1, provider="local"))
    await bus.publish(_presence_event(2, provider="local"))
    result = await check_womb_ready(
        {"perception_feed": {"mode": "external"}}, bus
    )
    assert not result.live
    assert f"no {WOMB_PRESENCE_TYPE} presence event" in result.reason


@pytest.mark.asyncio
async def test_ready_external_live_despite_later_readiness_event(bus):
    await bus.publish(_presence_event(1, provider="external"))
    await bus.publish(_presence_event(2, provider="external"))
    await bus.publish(
        Event(
            timestamp=datetime.now(timezone.utc),
            source=WOMB_SOURCE,
            type="gestation.readiness",
            payload={"ready": True},
            salience=0.1,
        )
    )
    result = await check_womb_ready(
        {"perception_feed": {"mode": "external"}}, bus
    )
    assert result.live


@pytest.mark.asyncio
async def test_ready_external_not_live_without_bus():
    result = await check_womb_ready(
        {"perception_feed": {"mode": "external"}}, None
    )
    assert not result.live
    assert "no bus" in result.reason


@pytest.mark.asyncio
async def test_ready_external_not_live_when_server_time_raises():
    class BadBus:
        async def server_time_ms(self):
            raise RuntimeError("redis down")

        async def range(self, *args, **kwargs):
            return []

    result = await check_womb_ready(
        {"perception_feed": {"mode": "external"}}, BadBus()
    )
    assert not result.live
    assert "RuntimeError: redis down" in result.reason


@pytest.mark.asyncio
async def test_ready_external_not_live_when_event_outside_window(bus):
    await bus.publish(_presence_event(1, provider="external"))
    await asyncio.sleep(0.05)
    result = await check_womb_ready(
        {"perception_feed": {"mode": "external"}},
        bus,
        window_s=0.01,
    )
    assert not result.live
    assert f"no {WOMB_PRESENCE_TYPE} presence event" in result.reason


@pytest.mark.parametrize("window_s", [0.0, -1.0, float("nan")])
@pytest.mark.asyncio
async def test_check_womb_ready_rejects_bad_window(window_s):
    with pytest.raises(ValueError):
        await check_womb_ready(
            {"perception_feed": {"mode": "external"}}, None, window_s=window_s
        )


@pytest.mark.asyncio
async def test_live_local_live_with_two_advancing_events(bus):
    await bus.publish(_presence_event(1, provider="local"))
    await bus.publish(_presence_event(2, provider="local"))
    result = await check_womb_live(
        {"perception_feed": {"mode": "womb"}}, bus
    )
    assert result == WombLiveness(True, "local", "")


@pytest.mark.asyncio
async def test_live_local_not_live_with_one_event(bus):
    await bus.publish(_presence_event(1, provider="local"))
    result = await check_womb_live(
        {"perception_feed": {"mode": "womb"}}, bus
    )
    assert not result.live
    assert "only one presence event" in result.reason


@pytest.mark.asyncio
async def test_live_local_not_live_with_two_same_frame_events(bus):
    await bus.publish(_presence_event(7, provider="local"))
    await bus.publish(_presence_event(7, provider="local"))
    result = await check_womb_live(
        {"perception_feed": {"mode": "womb"}}, bus
    )
    assert not result.live
    assert "frame_index did not advance" in result.reason


@pytest.mark.asyncio
async def test_live_local_not_live_with_wrong_provider(bus):
    await bus.publish(_presence_event(1, provider="external"))
    await bus.publish(_presence_event(2, provider="external"))
    result = await check_womb_live(
        {"perception_feed": {"mode": "womb"}}, bus
    )
    assert not result.live
    assert f"no {WOMB_PRESENCE_TYPE} presence event" in result.reason


@pytest.mark.asyncio
async def test_live_external_live_with_two_advancing_events(bus):
    await bus.publish(_presence_event(10, provider="external"))
    await bus.publish(_presence_event(11, provider="external"))
    result = await check_womb_live(
        {"perception_feed": {"mode": "external"}}, bus
    )
    assert result == WombLiveness(True, "external", "")


@pytest.mark.asyncio
async def test_live_external_not_live_with_wrong_provider(bus):
    await bus.publish(_presence_event(1, provider="local"))
    await bus.publish(_presence_event(2, provider="local"))
    result = await check_womb_live(
        {"perception_feed": {"mode": "external"}}, bus
    )
    assert not result.live
    assert f"no {WOMB_PRESENCE_TYPE} presence event" in result.reason


@pytest.mark.asyncio
async def test_live_local_not_live_without_bus():
    result = await check_womb_live(
        {"perception_feed": {"mode": "womb"}}, None
    )
    assert not result.live
    assert "no bus" in result.reason


@pytest.mark.asyncio
async def test_live_local_not_live_when_server_time_raises():
    class BadBus:
        async def server_time_ms(self):
            raise RuntimeError("redis down")

        async def range(self, *args, **kwargs):
            return []

    result = await check_womb_live(
        {"perception_feed": {"mode": "womb"}}, BadBus()
    )
    assert not result.live
    assert "RuntimeError: redis down" in result.reason


@pytest.mark.parametrize("window_s", [0.0, -1.0, float("nan")])
@pytest.mark.asyncio
async def test_check_womb_live_rejects_bad_window(window_s):
    with pytest.raises(ValueError):
        await check_womb_live(
            {"perception_feed": {"mode": "womb"}}, None, window_s=window_s
        )


@pytest.mark.asyncio
async def test_external_provider_may_name_itself(bus):
    # A body adapter names itself; any non-empty name other than "local" is an
    # external provider.
    await bus.publish(_presence_event(10, provider="paracosmic"))
    await bus.publish(_presence_event(11, provider="paracosmic"))
    result = await check_womb_live({"perception_feed": {"mode": "off"}}, bus)
    assert result.live, result.reason
    assert result.provider == "external"


@pytest.mark.asyncio
async def test_empty_provider_name_is_not_a_provider(bus):
    await bus.publish(_presence_event(10, provider=""))
    await bus.publish(_presence_event(11, provider=""))
    result = await check_womb_live({"perception_feed": {"mode": "off"}}, bus)
    assert not result.live
