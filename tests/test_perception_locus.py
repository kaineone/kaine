# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""perception_locus: the physical XOR virtual arbiter in perception_state."""
from __future__ import annotations

from kaine.perception_state import (
    LOCI,
    effective_audio_capture,
    effective_video_capture,
    read_desired,
    write_desired_audio,
    write_desired_locus,
    write_desired_video,
)


def test_default_locus_is_physical(tmp_path):
    p = tmp_path / "desired.json"
    assert read_desired(p).locus == "physical"


def test_invalid_locus_falls_back_to_physical(tmp_path):
    p = tmp_path / "desired.json"
    d = write_desired_locus("teleporting-into-the-sun", path=p)
    assert d.locus == "physical"
    assert set(LOCI) == {"physical", "virtual", "off"}


def test_virtual_locus_forces_real_capture_off(tmp_path):
    p = tmp_path / "desired.json"
    # operator wants both real streams on...
    write_desired_audio(True, path=p)
    write_desired_video(True, path=p)
    assert effective_audio_capture(p) and effective_video_capture(p)
    # ...but switching to virtual takes the real camera/mic dark in one step.
    write_desired_locus("virtual", path=p)
    assert not effective_audio_capture(p)
    assert not effective_video_capture(p)
    # the desired flags are preserved, just gated — back to physical restores.
    write_desired_locus("physical", path=p)
    assert effective_audio_capture(p) and effective_video_capture(p)


def test_off_locus_keeps_everything_dark(tmp_path):
    p = tmp_path / "desired.json"
    write_desired_audio(True, path=p)
    write_desired_locus("off", path=p)
    assert not effective_audio_capture(p) and not effective_video_capture(p)


def test_lock_persists_across_locus_writes(tmp_path):
    p = tmp_path / "desired.json"
    write_desired_locus("physical", locked=True, path=p)
    assert read_desired(p).locus_locked is True
    # changing locus without specifying locked leaves the lock intact
    write_desired_locus("virtual", path=p)
    assert read_desired(p).locus_locked is True
    write_desired_locus("physical", locked=False, path=p)
    assert read_desired(p).locus_locked is False


# --- entity self-switch controller -----------------------------------------
import asyncio  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402

from kaine.bus.config import BusConfig  # noqa: E402
from kaine.bus.schema import validate_event  # noqa: E402
from kaine.modules.perception.module import PerceptionLocus  # noqa: E402


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus

    client = fakeredis.FakeRedis(decode_responses=True)
    yield AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    await client.aclose()


async def _emit_switch(bus, locus: str):
    await bus.publish(validate_event(
        source="volition", type="intent.perception.switch",
        payload={"locus": locus}, salience=0.6,
        timestamp=datetime.now(timezone.utc)))


async def _wait_type(bus, stream, etype, timeout=3.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for _id, ev in await bus.read(stream, last_id="0", count=50, block_ms=100):
            if ev.type == etype:
                return ev
        await asyncio.sleep(0.05)
    return None


@pytest.mark.asyncio
async def test_self_switch_applied_when_policy_allows(bus, tmp_path):
    p = tmp_path / "desired.json"
    m = PerceptionLocus(bus, allow_self_switch=True, min_dwell_s=0.0, desired_path=p)
    await m.initialize()
    try:
        await _emit_switch(bus, "virtual")
        ev = await _wait_type(bus, "perception.out", "perception.locus.changed")
        assert ev is not None and ev.payload["locus"] == "virtual"
        assert read_desired(p).locus == "virtual"
    finally:
        await m.shutdown()


@pytest.mark.asyncio
async def test_self_switch_denied_by_default_policy(bus, tmp_path):
    p = tmp_path / "desired.json"
    m = PerceptionLocus(bus, allow_self_switch=False, desired_path=p)
    await m.initialize()
    try:
        await _emit_switch(bus, "virtual")
        ev = await _wait_type(bus, "perception.out", "perception.locus.denied")
        assert ev is not None and ev.payload["reason"] == "self-switch disabled by policy"
        assert read_desired(p).locus == "physical"  # unchanged
    finally:
        await m.shutdown()


@pytest.mark.asyncio
async def test_self_switch_denied_when_locked(bus, tmp_path):
    p = tmp_path / "desired.json"
    write_desired_locus("physical", locked=True, path=p)
    m = PerceptionLocus(bus, allow_self_switch=True, min_dwell_s=0.0, desired_path=p)
    await m.initialize()
    try:
        await _emit_switch(bus, "virtual")
        ev = await _wait_type(bus, "perception.out", "perception.locus.denied")
        assert ev is not None and ev.payload["reason"] == "locus locked by operator"
        assert read_desired(p).locus == "physical"
    finally:
        await m.shutdown()
