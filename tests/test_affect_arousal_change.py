# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.affect import Affect

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


PERCEPTUAL_SOURCES = [
    ("vision.out", "vision", "vision.report"),
    ("audition.out", "audition", "audition.perception"),
]


async def _arousal_delta(bus, stream, source, event_type, payload):
    affect = Affect(bus, publish_interval_s=999.0)
    base = affect._state.arousal
    event = Event(
        source=source,
        type=event_type,
        payload=payload,
        salience=0.8,
        timestamp=datetime.now(timezone.utc),
    )
    await affect._handle_peer_event(stream, event)
    return affect._state.arousal - base


@pytest.mark.parametrize("stream,source,event_type", PERCEPTUAL_SOURCES)
async def test_change_alert_uses_change_ratio(bus, stream, source, event_type):
    delta = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": True, "normalised_error": 0.99, "normalised_change": 3.0},
    )
    assert delta == pytest.approx(0.15 * 2.0)


@pytest.mark.parametrize("stream,source,event_type", PERCEPTUAL_SOURCES)
async def test_error_alert_unchanged_with_change_field(bus, stream, source, event_type):
    delta = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": True, "normalised_error": 3.0, "normalised_change": 0.5},
    )
    assert delta == pytest.approx(0.15 * 2.0)


@pytest.mark.parametrize("stream,source,event_type", PERCEPTUAL_SOURCES)
async def test_error_alert_unchanged_without_change_field(bus, stream, source, event_type):
    delta = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": True, "normalised_error": 3.0},
    )
    assert delta == pytest.approx(0.15 * 2.0)


@pytest.mark.parametrize("stream,source,event_type", PERCEPTUAL_SOURCES)
async def test_max_of_error_and_change_ratios(bus, stream, source, event_type):
    delta_change_wins = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": True, "normalised_error": 2.0, "normalised_change": 3.5},
    )
    delta_error_wins = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": True, "normalised_error": 3.5, "normalised_change": 2.0},
    )
    assert delta_change_wins == pytest.approx(0.15 * 2.5)
    assert delta_error_wins == pytest.approx(0.15 * 2.5)


@pytest.mark.parametrize("stream,source,event_type", PERCEPTUAL_SOURCES)
async def test_missing_change_field_backward_compatible(bus, stream, source, event_type):
    delta = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": True, "normalised_error": 2.5},
    )
    assert delta == pytest.approx(0.15 * 1.5)


@pytest.mark.parametrize("stream,source,event_type", PERCEPTUAL_SOURCES)
async def test_missing_both_ratios_leaves_arousal_unchanged(bus, stream, source, event_type):
    delta = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": True},
    )
    assert delta == pytest.approx(0.0)


@pytest.mark.parametrize("stream,source,event_type", PERCEPTUAL_SOURCES)
async def test_change_ratio_cap(bus, stream, source, event_type):
    delta = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": True, "normalised_error": 0.5, "normalised_change": 50.0},
    )
    assert delta == pytest.approx(0.15 * 4.0)


@pytest.mark.parametrize("stream,source,event_type", PERCEPTUAL_SOURCES)
@pytest.mark.parametrize("bad_change", [float("nan"), float("inf"), None, "abc"])
async def test_defensive_reading_ignores_invalid_change_ratio(
    bus, stream, source, event_type, bad_change
):
    delta = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": True, "normalised_error": 0.99, "normalised_change": bad_change},
    )
    assert delta == pytest.approx(0.0)


@pytest.mark.parametrize("stream,source,event_type", PERCEPTUAL_SOURCES)
async def test_defensive_reading_ignores_invalid_error_ratio(bus, stream, source, event_type):
    delta = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": True, "normalised_error": float("nan"), "normalised_change": 3.0},
    )
    assert delta == pytest.approx(0.15 * 2.0)


@pytest.mark.parametrize("stream,source,event_type", PERCEPTUAL_SOURCES)
async def test_non_alert_reports_do_not_raise_arousal(bus, stream, source, event_type):
    delta_explicit_false = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"alert": False, "normalised_error": 5.0, "normalised_change": 5.0},
    )
    delta_missing_alert = await _arousal_delta(
        bus,
        stream,
        source,
        event_type,
        {"normalised_change": 5.0},
    )
    assert delta_explicit_false == pytest.approx(0.0)
    assert delta_missing_alert == pytest.approx(0.0)
