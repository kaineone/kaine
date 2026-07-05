# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.thymos.drives import Drive, DriveSet


def test_drive_builds_with_signal():
    d = Drive(name="x", build_rate=0.5, decay_rate=0.0)
    d.tick(dt=1.0, signal=1.0)
    assert d.value == pytest.approx(0.5)


def test_drive_decays_without_signal():
    d = Drive(name="x", build_rate=0.0, decay_rate=0.2, value=0.5)
    d.tick(dt=1.0, signal=0.0)
    assert d.value == pytest.approx(0.3)


def test_drive_clamps_to_unit_range():
    d = Drive(name="x", build_rate=2.0, decay_rate=0.0)
    d.tick(dt=2.0, signal=1.0)
    assert d.value == 1.0


def test_drive_threshold_crossing_fires_once():
    d = Drive(name="x", build_rate=1.0, decay_rate=0.0, threshold=0.7)
    d.tick(dt=1.0, signal=1.0)  # value goes to 1.0
    assert d.consume_crossing() is True
    # No re-fire while still above threshold.
    assert d.consume_crossing() is False


def test_drive_hysteresis_requires_drop_below_band():
    d = Drive(name="x", build_rate=1.0, decay_rate=0.0, threshold=0.7, hysteresis_fraction=0.9)
    d.tick(dt=1.0, signal=1.0)
    assert d.consume_crossing() is True
    # Bring just under threshold (still > 0.63).
    d.value = 0.65
    d.tick(dt=0.1, signal=0)
    assert d.consume_crossing() is False  # not below band
    # Drop below hysteresis band (0.7 * 0.9 = 0.63).
    d.value = 0.5
    d.tick(dt=0.1, signal=0)
    # Re-cross
    d.value = 0.8
    assert d.consume_crossing() is True


def test_drive_reset():
    d = Drive(name="x", value=0.9)
    d.tick(dt=0, signal=0)
    d.consume_crossing()
    d.reset()
    assert d.value == 0.0


def test_driveset_default_construction():
    s = DriveSet()
    names = [d.name for d in s.all()]
    assert set(names) == {"curiosity", "boredom", "social_drive", "restlessness"}


def test_driveset_tick_returns_crossings():
    s = DriveSet()
    s.curiosity.threshold = 0.1
    s.curiosity.build_rate = 1.0
    crossings = s.tick(dt=1.0, novelty_signal=1.0)
    names = [c.name for c in crossings]
    assert "curiosity" in names


def test_driveset_reset_all():
    s = DriveSet()
    s.curiosity.value = 0.8
    s.boredom.value = 0.5
    s.reset_all()
    assert s.curiosity.value == 0.0
    assert s.boredom.value == 0.0


def test_driveset_to_dict():
    s = DriveSet()
    d = s.to_dict()
    assert set(d.keys()) == {"curiosity", "boredom", "social_drive", "restlessness"}
