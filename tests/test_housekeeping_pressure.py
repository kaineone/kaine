# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine/housekeeping_pressure.py."""

import pytest

from kaine.housekeeping_pressure import HousekeepingPressure, shared_pressure


def test_initial_terms_are_zero():
    p = HousekeepingPressure()
    assert p.disk == 0.0
    assert p.memory == 0.0
    assert p.episodic == 0.0
    assert p.value() == 0.0


def test_set_from_sleep():
    p = HousekeepingPressure()
    p.set_from_sleep({"terms": {"disk": 1.5, "memory": 0.25, "episodic": 0.0}})
    assert p.disk == 1.5
    assert p.memory == 0.25
    assert p.episodic == 0.0
    assert p.value() == pytest.approx(1.75)


def test_set_from_sleep_without_terms_keeps_last_value():
    p = HousekeepingPressure()
    p.set_from_sleep({"terms": {"disk": 1.5, "memory": 0.5, "episodic": 0.25}})
    p.set_from_sleep({"enabled": False})
    assert p.value() == pytest.approx(2.25)
    p.set_from_sleep({})
    assert p.value() == pytest.approx(2.25)
    p.set_from_sleep({"terms": "not a dict"})
    assert p.value() == pytest.approx(2.25)


def test_set_from_sleep_bad_values_give_zero():
    p = HousekeepingPressure()
    p.set_from_sleep(
        {"terms": {"disk": float("nan"), "memory": -1.0, "episodic": "x"}}
    )
    assert p.disk == 0.0
    assert p.memory == 0.0
    assert p.episodic == 0.0
    p.set_from_sleep({"terms": {"disk": float("inf"), "memory": True}})
    assert p.value() == 0.0
    # Missing keys give 0.0 while the good value is taken.
    p.set_from_sleep({"terms": {"disk": 2.0}})
    assert p.disk == 2.0
    assert p.memory == 0.0
    assert p.episodic == 0.0


def test_note_floor_disk_excess_keeps_the_larger():
    p = HousekeepingPressure()
    p.set_from_sleep({"terms": {"disk": 1.0, "memory": 0.0, "episodic": 0.0}})
    p.note_floor_disk_excess(0.5)
    assert p.disk == 1.0
    p.note_floor_disk_excess(2.5)
    assert p.disk == 2.5
    p.note_floor_disk_excess(float("nan"))
    assert p.disk == 2.5
    p.note_floor_disk_excess(-1.0)
    assert p.disk == 2.5
    p.note_floor_disk_excess(float("inf"))
    assert p.disk == 2.5


def test_next_sleep_replaces_floor_excess():
    p = HousekeepingPressure()
    p.note_floor_disk_excess(3.0)
    assert p.disk == 3.0
    p.set_from_sleep({"terms": {"disk": 0.5, "memory": 0.0, "episodic": 0.0}})
    assert p.disk == 0.5


def test_reset():
    p = HousekeepingPressure()
    p.set_from_sleep({"terms": {"disk": 1.0, "memory": 2.0, "episodic": 3.0}})
    p.reset()
    assert p.disk == 0.0
    assert p.memory == 0.0
    assert p.episodic == 0.0
    assert p.value() == 0.0


def test_shared_pressure_returns_one_object():
    assert shared_pressure() is shared_pressure()
    assert isinstance(shared_pressure(), HousekeepingPressure)
