# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live stream consumers start at the stream tail and never replay history."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus, tail_id
from kaine.bus.config import BusConfig
from kaine.modules.interoception.module import Interoception


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _sleep_event(type_: str) -> Event:
    return Event(
        source="sleep",
        type=type_,
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


async def _settle(cond, tries: int = 100) -> None:
    for _ in range(tries):
        if cond():
            return
        await asyncio.sleep(0.01)


# ---- the helper -----------------------------------------------------------


@pytest.mark.asyncio
async def test_tail_id_missing_stream_is_zero(bus: AsyncBus):
    assert await tail_id(bus, "no.such.stream") == "0-0"


@pytest.mark.asyncio
async def test_tail_id_emptied_stream_is_zero(bus: AsyncBus):
    entry_id = await bus.client.xadd("some.stream", {"k": "v"})
    await bus.client.xdel("some.stream", entry_id)
    assert await tail_id(bus, "some.stream") == "0-0"


@pytest.mark.asyncio
async def test_tail_id_populated_stream_is_newest_id(bus: AsyncBus):
    await bus.client.xadd("some.stream", {"k": "1"})
    newest = await bus.client.xadd("some.stream", {"k": "2"})
    newest = newest.decode() if isinstance(newest, bytes) else newest
    assert await tail_id(bus, "some.stream") == newest


@pytest.mark.asyncio
async def test_tail_id_swallows_lookup_errors():
    class Broken:
        class client:  # noqa: N801
            @staticmethod
            async def xrevrange(*_a, **_k):
                raise RuntimeError("down")

    assert await tail_id(Broken(), "x") == "0-0"


@pytest.mark.asyncio
async def test_tail_id_strict_raises_on_lookup_error():
    class Broken:
        class client:  # noqa: N801
            @staticmethod
            async def xrevrange(*_a, **_k):
                raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        await tail_id(Broken(), "x", strict=True)


# ---- interoception --------------------------------------------------------


@pytest.mark.asyncio
async def test_interoception_ignores_sleep_history_at_boot(bus: AsyncBus):
    pytest.importorskip("torch")
    from tests.test_interoception_sleep_flag import FakeMetricsReader, NeverAlertDetector

    await bus.publish(_sleep_event("sleep.sleep.started"))
    await bus.publish(_sleep_event("sleep.sleep.completed"))
    await bus.publish(_sleep_event("sleep.sleep.started"))  # dangling: crash mid-sleep

    mod = Interoception(bus, reader=FakeMetricsReader(), detector=NeverAlertDetector())
    mod._fatigue._value = 40.0  # as if restored from the checkpoint
    await mod.initialize()
    try:
        await asyncio.sleep(0.3)
        assert mod._fatigue.value == 40.0
        assert mod._in_sleep is False
        assert mod._fatigue.faster_decay is False
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_interoception_still_resets_on_new_completion(bus: AsyncBus):
    pytest.importorskip("torch")
    from tests.test_interoception_sleep_flag import FakeMetricsReader, NeverAlertDetector

    await bus.publish(_sleep_event("sleep.sleep.completed"))
    mod = Interoception(bus, reader=FakeMetricsReader(), detector=NeverAlertDetector())
    mod._fatigue._value = 40.0
    await mod.initialize()
    try:
        await bus.publish(_sleep_event("sleep.sleep.started"))
        await _settle(lambda: mod._in_sleep)
        assert mod._in_sleep is True
        await bus.publish(_sleep_event("sleep.sleep.completed"))
        await _settle(lambda: not mod._in_sleep)
        assert mod._in_sleep is False
        assert mod._fatigue.value == 0.0
    finally:
        await mod.shutdown()


# ---- other converted consumers: the cursor sits at the tail after initialize


async def _seed(bus: AsyncBus, stream: str) -> str:
    await bus.client.xadd(stream, {"payload": "{}"})
    newest = await bus.client.xadd(stream, {"payload": "{}"})
    return newest.decode() if isinstance(newest, bytes) else newest


@pytest.mark.asyncio
async def test_effectors_intent_cursor_starts_at_tail(bus: AsyncBus, tmp_path):
    from kaine.modules.effectors.module import Effectors

    mod = Effectors(
        bus,
        sandbox_path=tmp_path / "files",
        audit_log_path=tmp_path / "audit.log",
        notification_fallback_log=tmp_path / "n.log",
    )
    newest = await _seed(bus, mod._intent_stream)
    await mod.initialize()
    try:
        assert mod._intent_cursor == newest
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_perceptual_locus_intent_cursor_starts_at_tail(bus: AsyncBus):
    from kaine.modules.perceptual_locus.module import PerceptualLocus

    mod = PerceptualLocus(bus)
    newest = await _seed(bus, mod._intent_stream)
    await mod.initialize()
    try:
        assert mod._intent_cursor == newest
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_vision_audition_sequence_sleep_cursors_start_at_tail(bus: AsyncBus):
    pytest.importorskip("torch")
    from kaine.modules.audition.module import Audition
    from kaine.modules.sequence.anomaly import RollingZScoreAnomaly
    from kaine.modules.sequence.featurizer import SnapshotFeaturizer
    from kaine.modules.sequence.module import Sequence
    from kaine.modules.sequence.rumination import RecurrenceRuminationDetector
    from kaine.modules.vision import Vision
    from tests.test_audition_module import _make_audition
    from tests.test_sequence_module import FakeNetwork
    from tests.test_vision_module import FakeEncoder

    mods = (
        (Vision(bus, encoder=FakeEncoder([[1.0, 0.0, 0.0, 0.0]])), "sleep.out"),
        (_make_audition(bus), Audition._SLEEP_STREAM),
        (
            Sequence(
                bus,
                featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
                network=FakeNetwork(units=4),
                anomaly=RollingZScoreAnomaly(window=4),
                rumination=RecurrenceRuminationDetector(window=4, threshold=4),
            ),
            "sleep.out",
        ),
    )
    for mod, stream in mods:
        newest = await _seed(bus, stream)
        await mod.initialize()
        try:
            assert mod._sleep_cursor == newest, type(mod).__name__
        finally:
            await mod.shutdown()
