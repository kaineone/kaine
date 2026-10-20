# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for welfare sleep-reset end counts and open-crossing flags (paper 6.2)."""

import math

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.evaluation.observers.welfare_observer import _DEFICIT_DRIVES, AffectWelfareTally
from kaine.modules.affect import Affect
from kaine.modules.affect.drives import Drive, DriveSet

pytestmark = pytest.mark.asyncio


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


def test_drive_sleep_reset_counts_latched_deficit():
    d = Drive(name="boredom", build_rate=0.04, decay_rate=0.0045, threshold=0.7, relief_gain=0.3)
    d.value = 0.9
    assert d.consume_crossing()
    d.sleep_reset()
    assert d.reset_ends == 1
    assert d.value == 0.0
    assert d._has_fired is False
    assert d.own_ends == 0
    assert d.other_ends == 0

    # No latch: nothing is counted.
    d.value = 0.9
    d.sleep_reset()
    assert d.reset_ends == 1
    assert d.value == 0.0
    assert d._has_fired is False

    # Curiosity is heterostatic and never counts a sleep reset.
    c = Drive(name="curiosity", heterostatic=True, build_rate=0.05, decay_rate=0.00096, threshold=0.7, relief_gain=0.0)
    c.value = 0.9
    assert c.consume_crossing()
    c.sleep_reset()
    assert c.reset_ends == 0

    # A plain reset() does not count.
    d.value = 0.9
    assert d.consume_crossing()
    d.reset()
    assert d.reset_ends == 1


def test_drive_set_reset_deficits_counts_and_open():
    ds = DriveSet()
    ds.boredom.value = 0.9
    ds.restlessness.value = 0.9
    assert ds.boredom.consume_crossing()
    assert ds.restlessness.consume_crossing()
    ds.social_drive.value = 0.1
    ds.curiosity.value = 0.9
    assert ds.curiosity.consume_crossing()

    ds.reset_deficits()

    assert ds.boredom.reset_ends == 1
    assert ds.restlessness.reset_ends == 1
    assert ds.social_drive.reset_ends == 0
    assert ds.curiosity.reset_ends == 0

    open_flags = ds.open_to_dict()
    assert set(open_flags) == {"boredom", "social_drive", "restlessness"}
    assert open_flags == {
        "boredom": False,
        "social_drive": False,
        "restlessness": False,
    }

    ds.boredom.value = 0.9
    assert ds.boredom.consume_crossing()
    assert ds.open_to_dict()["boredom"] is True


def test_load_reset_ends_ignores_bad_values_and_restores_good_ones():
    ds = DriveSet()
    ds.boredom.reset_ends = 5
    ds.restlessness.reset_ends = 3

    ds.load_reset_ends({
        "boredom": True,  # bool: ignored
        "restlessness": -1,  # negative: ignored
        "social_drive": 2.5,  # float: ignored
        "unknown": 4,  # unknown name: ignored
        "curiosity": 7,  # heterostatic: ignored
    })
    assert ds.boredom.reset_ends == 5
    assert ds.restlessness.reset_ends == 3
    assert ds.social_drive.reset_ends == 0

    ds.load_reset_ends("not a dict")
    assert ds.boredom.reset_ends == 5

    ds.load_reset_ends({"boredom": 10, "restlessness": 1, "social_drive": 4})
    assert ds.boredom.reset_ends == 10
    assert ds.restlessness.reset_ends == 1
    assert ds.social_drive.reset_ends == 4


async def test_serialize_deserialize_round_trips_reset_ends(bus):
    affect = Affect(bus, clock=lambda: 0.0, publish_interval_s=1.0)
    affect.drives.boredom.reset_ends = 7
    affect.drives.restlessness.reset_ends = 4

    state = affect.serialize()
    assert state["drive_reset_ends"] == {
        "boredom": 7,
        "restlessness": 4,
        "social_drive": 0,
    }

    affect2 = Affect(bus, clock=lambda: 0.0, publish_interval_s=1.0)
    affect2.deserialize(state)
    assert affect2.drives.boredom.reset_ends == 7
    assert affect2.drives.restlessness.reset_ends == 4
    assert affect2.drives.social_drive.reset_ends == 0


async def test_reset_payload_reports_sleep_reset_end_and_cleared_open_flag(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    affect.drives.boredom.value = 0.9
    assert affect.drives.boredom.consume_crossing()
    t[0] = 5.0
    await affect.affective_reset()

    entries = await bus.read("affect.out", last_id="0", count=500)
    resets = [ev.payload for _, ev in entries if ev.type == "affect.state" and ev.payload.get("reset")]
    assert resets
    payload = resets[-1]

    assert payload["drive_reset_ends"]["boredom"] == 1
    assert payload["drive_open"]["boredom"] is False
    assert payload["drive_ends"]["boredom"] == {"own": 0, "other": 0}
    for counts in payload["drive_ends"].values():
        assert set(counts) == {"own", "other"}


async def test_periodic_payload_reports_open_crossing(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    affect.drives.boredom.value = 0.9
    assert affect.drives.boredom.consume_crossing()
    t[0] = 5.0
    await affect._maybe_publish_state()

    payload = await _last_state_payload(bus)
    assert payload["drive_open"]["boredom"] is True
    assert payload["drive_reset_ends"]["boredom"] == 0


def test_tally_reset_ends_sequence_counts_increases_and_re_baselines():
    tally = AffectWelfareTally(negative_valence_bar=0.25, max_gap_s=60.0)
    for value in (0, 1, 1, 3):
        tally.observe_state(value, 0.0, drive_reset_ends={"boredom": value})
    snap = tally.snapshot()
    assert snap["boredom_sleep_reset_ends"] == 3

    tally2 = AffectWelfareTally(negative_valence_bar=0.25, max_gap_s=60.0)
    tally2.observe_state(0, 0.0, drive_reset_ends={"boredom": 5})
    tally2.observe_state(1, 0.0, drive_reset_ends={"boredom": 2})
    tally2.observe_state(2, 0.0, drive_reset_ends={"boredom": 3})
    assert tally2.snapshot()["boredom_sleep_reset_ends"] == 1


def test_tally_open_flag_tracks_latest_and_changes():
    tally = AffectWelfareTally(negative_valence_bar=0.25, max_gap_s=60.0)
    tally.observe_state(0, 0.0, drive_open={"boredom": True})
    tally.observe_state(1, 0.0, drive_open={"boredom": False})
    assert tally.snapshot()["boredom_open_crossings"] == 0

    tally2 = AffectWelfareTally(negative_valence_bar=0.25, max_gap_s=60.0)
    tally2.observe_state(0, 0.0, drive_open={"boredom": False})
    tally2.observe_state(1, 0.0, drive_open={"boredom": True})
    assert tally2.snapshot()["boredom_open_crossings"] == 1


def test_tally_open_none_and_malformed_ignored():
    tally = AffectWelfareTally(negative_valence_bar=0.25, max_gap_s=60.0)
    tally.observe_state(0, 0.0)
    assert tally.snapshot()["boredom_open_crossings"] is None

    tally2 = AffectWelfareTally(negative_valence_bar=0.25, max_gap_s=60.0)
    tally2.observe_state(0, 0.0, drive_open={"boredom": "true"})
    tally2.observe_state(1, 0.0, drive_open={"boredom": None})
    assert tally2.snapshot()["boredom_open_crossings"] is None


def test_tally_new_args_do_not_change_existing_counts():
    tally = AffectWelfareTally(negative_valence_bar=0.25, max_gap_s=60.0)
    tally.observe_state(0, 0.0, drive_ends={"boredom": {"own": 0, "other": 0}})
    tally.observe_state(0.5, 0.0, drive_ends={"boredom": {"own": 2, "other": 1}})
    tally.observe_state(
        1,
        0.0,
        drive_reset_ends={"boredom": 5},
        drive_open={"boredom": True},
    )
    snap = tally.snapshot()
    assert tally._ends["boredom"] == [2, 1]
    assert snap["boredom_uncontrolled_share"] == 1.0 / 3.0


def test_tally_tenth_boot_case():
    tally = AffectWelfareTally(negative_valence_bar=0.25, max_gap_s=60.0)
    baseline_ends = {drive: {"own": 0, "other": 0} for drive in _DEFICIT_DRIVES}
    baseline_reset = {drive: 0 for drive in _DEFICIT_DRIVES}
    baseline_open = {drive: False for drive in _DEFICIT_DRIVES}
    tally.observe_state(0, 0.0, drive_ends=baseline_ends, drive_reset_ends=baseline_reset, drive_open=baseline_open)

    final_ends = {drive: {"own": 0, "other": 0} for drive in _DEFICIT_DRIVES}
    final_ends["boredom"] = {"own": 85, "other": 8}
    final_reset = {drive: 0 for drive in _DEFICIT_DRIVES}
    final_reset["boredom"] = 2
    final_open = {drive: False for drive in _DEFICIT_DRIVES}
    tally.observe_state(1, 0.0, drive_ends=final_ends, drive_reset_ends=final_reset, drive_open=final_open)

    snap = tally.snapshot()
    assert math.isclose(snap["boredom_uncontrolled_share"], 8.0 / 93.0)
    assert snap["boredom_sleep_reset_ends"] == 2
    assert snap["boredom_open_crossings"] == 0
