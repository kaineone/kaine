# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The affect state event carries each drive's threshold flag and crossing-end counts for the welfare records (paper 6.2, A.4)."""

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.affect import Affect
from kaine.modules.affect.drives import DriveSet

pytestmark = pytest.mark.asyncio

DRIVE_NAMES = {"curiosity", "boredom", "social_drive", "restlessness"}


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


async def _last_state_payload(bus):
    entries = await bus.read("affect.out", last_id="0", count=500)
    states = [ev.payload for _, ev in entries if ev.type == "affect.state"]
    assert states
    return states[-1]


async def test_periodic_state_flags_deprived_drive(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    affect.drives.curiosity.value = 0.9
    affect.drives.boredom.value = 0.2
    t[0] = 5.0
    await affect._maybe_publish_state()
    payload = await _last_state_payload(bus)
    expected = {
        "curiosity": True,
        "boredom": False,
        "social_drive": False,
        "restlessness": False,
    }
    assert payload["drive_above"] == expected
    assert all(isinstance(v, bool) for v in payload["drive_above"].values())


async def test_threshold_is_inclusive(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    affect.drives.curiosity.value = affect.drives.curiosity.threshold
    t[0] = 5.0
    await affect._maybe_publish_state()
    payload = await _last_state_payload(bus)
    assert payload["drive_above"]["curiosity"] is True

    affect.drives.curiosity.value = affect.drives.curiosity.threshold - 1e-9
    t[0] += 5.0
    await affect._maybe_publish_state()
    payload = await _last_state_payload(bus)
    assert payload["drive_above"]["curiosity"] is False


async def test_periodic_state_carries_end_counts(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    c = affect.drives.curiosity
    c.value = 0.9
    assert c.consume_crossing()
    c.relieve_rate(1.0, 100.0, own=True)
    assert c.own_ends == 1

    b = affect.drives.boredom
    b.value = 0.9
    assert b.consume_crossing()
    b.relieve_fraction(1.0, own=False)
    assert b.other_ends == 1

    t[0] = 5.0
    await affect._maybe_publish_state()
    payload = await _last_state_payload(bus)
    expected = {
        "curiosity": {"own": 1, "other": 0},
        "boredom": {"own": 0, "other": 1},
        "social_drive": {"own": 0, "other": 0},
        "restlessness": {"own": 0, "other": 0},
    }
    assert payload["drive_ends"] == expected
    for counts in payload["drive_ends"].values():
        assert type(counts["own"]) is int
        assert type(counts["other"]) is int


async def test_reset_state_keeps_counts_and_clears_flags(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    c = affect.drives.curiosity
    c.value = 0.9
    assert c.consume_crossing()
    c.relieve_rate(1.0, 100.0, own=True)
    c.value = 0.9
    await affect.affective_reset()
    entries = await bus.read("affect.out", last_id="0", count=500)
    resets = [ev.payload for _, ev in entries if ev.type == "affect.state" and ev.payload.get("reset")]
    assert resets
    payload = resets[-1]
    assert payload["drive_ends"]["curiosity"] == {"own": 1, "other": 0}
    assert all(v is False for v in payload["drive_above"].values())


async def test_fields_are_content_free(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    t[0] = 5.0
    await affect._maybe_publish_state()
    payload = await _last_state_payload(bus)
    assert set(payload["drive_above"]) == DRIVE_NAMES
    assert set(payload["drive_ends"]) == DRIVE_NAMES
    for counts in payload["drive_ends"].values():
        assert set(counts) == {"own", "other"}


async def test_drive_set_above_to_dict():
    drives = DriveSet()
    assert drives.above_to_dict() == {
        "curiosity": False,
        "boredom": False,
        "social_drive": False,
        "restlessness": False,
    }
    drives.social_drive.value = 0.7
    assert drives.above_to_dict() == {
        "curiosity": False,
        "boredom": False,
        "social_drive": True,
        "restlessness": False,
    }


async def test_drive_set_above_to_dict_returns_python_bools():
    np = pytest.importorskip("numpy")
    drives = DriveSet()
    drives.curiosity.value = np.float64(0.9)
    flags = drives.above_to_dict()
    assert flags["curiosity"] is True
    assert all(type(v) is bool for v in flags.values())
