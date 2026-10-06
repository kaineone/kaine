# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import time
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.acoustic import FakeAcousticEncoder
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.module import Chronos
from kaine.modules.topos.module import Topos


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class _FakeEncoder:
    """Minimal Topos encoder double — no DINOv2 download, deterministic latent."""

    model_id = "fake/encoder-sleep"
    latent_dim = 4

    def __init__(self) -> None:
        self.calls = 0

    async def load(self) -> None:  # noqa: D401
        return None

    async def shutdown(self) -> None:
        return None

    async def encode(self, image):  # noqa: ARG002
        self.calls += 1
        return [float(self.calls % 7), 0.0, 0.0, 0.0]


def _make_audition(bus: AsyncBus, **overrides) -> Audition:
    overrides.setdefault("stt_client", FakeSTTClient(responses=["hello world"]))
    overrides.setdefault("emotion_classifier", FakeEmotionClassifier())
    overrides.setdefault("stt_model", "fake-stt")
    overrides.setdefault("transcription_enabled", True)
    return Audition(bus, **overrides)


def _sleep_event(event_type: str) -> Event:
    return Event(
        source="hypnos",
        type=event_type,
        payload={},
        salience=0.1,
        timestamp=datetime.now(timezone.utc),
    )


async def _poll_for(predicate, timeout=2.0, interval=0.05):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition was not met within timeout")


async def _close_module(module) -> None:
    await module.shutdown()
    for task in list(getattr(module, "_tasks", [])):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.asyncio
async def test_nonblocking_dollar_read_is_refused(bus):
    with pytest.raises(ValueError, match="non-blocking read of 's'"):
        await bus.read_entries("s", last_id="$", block_ms=0)
    with pytest.raises(ValueError, match="non-blocking read of 's'"):
        await bus.read("s", last_id="$", block_ms=0)
    with pytest.raises(ValueError, match="non-blocking read of 's'"):
        await bus.read_entries_block({"s": "$"}, block_ms=0)


@pytest.mark.asyncio
async def test_blocking_dollar_read_still_works(bus):
    async def _publish_after_delay():
        await asyncio.sleep(0.1)
        # source="s_src" would route to s_src.out, so xadd directly to s.
        await bus.client.xadd(
            "s",
            {
                "source": "s_src",
                "type": "s.ping",
                "payload": "{}",
                "salience": "0.1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    publisher = asyncio.create_task(_publish_after_delay())
    try:
        entries, last_scanned = await bus.read_entries(
            "s", last_id="$", count=10, block_ms=2000
        )
        assert len(entries) == 1
        assert last_scanned is not None
        _, event = entries[0]
        assert event.source == "s_src"
        assert event.type == "s.ping"
    finally:
        publisher.cancel()
        try:
            await publisher
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_chronos_suspends_forward_head_during_sleep(bus):
    now = {"t": 0.0}
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: now["t"]),
        forward_prediction=True,
        reservoir_seed=7,
        clock=lambda: now["t"],
    )
    await chronos.initialize()
    try:
        assert chronos._pred_head is not None

        await bus.publish(_sleep_event("hypnos.sleep.started"))
        await _poll_for(lambda: chronos._pred_head.suspended)
        assert chronos._in_hypnos

        await bus.publish(_sleep_event("hypnos.sleep.completed"))
        await _poll_for(lambda: not chronos._pred_head.suspended)
        assert not chronos._in_hypnos
    finally:
        await _close_module(chronos)


@pytest.mark.asyncio
async def test_chronos_sees_sleep_on_an_empty_stream_too(bus):
    now = {"t": 0.0}
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: now["t"]),
        forward_prediction=True,
        reservoir_seed=7,
        clock=lambda: now["t"],
    )
    await chronos.initialize()
    try:
        assert chronos._hypnos_cursor == "0-0"

        await bus.publish(_sleep_event("hypnos.sleep.started"))
        await _poll_for(lambda: chronos._pred_head.suspended)

        await bus.publish(_sleep_event("hypnos.sleep.completed"))
        await _poll_for(lambda: not chronos._pred_head.suspended)
    finally:
        await _close_module(chronos)


@pytest.mark.asyncio
async def test_chronos_ignores_sleep_published_before_boot(bus):
    await bus.publish(_sleep_event("hypnos.sleep.started"))

    now = {"t": 0.0}
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: now["t"]),
        forward_prediction=True,
        reservoir_seed=7,
        clock=lambda: now["t"],
    )
    await chronos.initialize()
    try:
        await asyncio.sleep(0.3)
        assert not chronos._pred_head.suspended
        assert not chronos._in_hypnos

        # A fresh sleep event after boot must still be seen.
        await bus.publish(_sleep_event("hypnos.sleep.started"))
        await _poll_for(lambda: chronos._pred_head.suspended)
    finally:
        await _close_module(chronos)


@pytest.mark.asyncio
async def test_topos_suspends_forward_model_during_sleep(bus):
    topos = Topos(bus, encoder=_FakeEncoder(), forward_prediction=True)
    await topos.initialize()
    try:
        assert topos._forward_model is not None

        await bus.publish(_sleep_event("hypnos.sleep.started"))
        await _poll_for(lambda: topos._forward_model.suspended)
        assert topos._in_hypnos

        await bus.publish(_sleep_event("hypnos.sleep.completed"))
        await _poll_for(lambda: not topos._forward_model.suspended)
        assert not topos._in_hypnos
    finally:
        await _close_module(topos)


@pytest.mark.asyncio
async def test_audition_still_suspends_during_sleep(bus):
    encoder = FakeAcousticEncoder(8)
    audition = _make_audition(bus, general_audition=True, acoustic_encoder=encoder)
    await audition.initialize()
    try:
        assert audition._forward_model is not None
        assert audition._acoustic_forward_model is not None

        await bus.publish(_sleep_event("hypnos.sleep.started"))
        await _poll_for(
            lambda: audition._forward_model.suspended
            and audition._acoustic_forward_model.suspended
        )
        assert audition._in_hypnos

        await bus.publish(_sleep_event("hypnos.sleep.completed"))
        await _poll_for(
            lambda: not audition._forward_model.suspended
            and not audition._acoustic_forward_model.suspended
        )
        assert not audition._in_hypnos
    finally:
        await _close_module(audition)
