# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Curiosity as heterostatic interest in the drive set (paper A.4)."""

import pytest

from kaine.modules.affect.drives import Drive, DriveSet
from kaine.modules.affect.goals import GoalLedger


def test_curiosity_defaults_are_heterostatic_interest():
    s = DriveSet()
    assert s.curiosity.decay_rate == pytest.approx(0.00096)
    assert s.curiosity.relief_gain == pytest.approx(0.0)
    assert s.curiosity.heterostatic is True
    assert s.boredom.heterostatic is False
    assert s.social_drive.heterostatic is False
    assert s.restlessness.heterostatic is False
    assert [d.name for d in s.deficits()] == ["boredom", "social_drive", "restlessness"]


def test_curiosity_equilibrium_matches_threshold_at_reference_progress():
    s = DriveSet()
    beta = s.curiosity.build_rate
    delta = s.curiosity.decay_rate
    u = 0.045
    eq = beta * u / (beta * u + delta)
    assert eq == pytest.approx(s.curiosity.threshold, abs=0.01)


def test_no_progress_no_interest():
    s = DriveSet()
    s.curiosity.value = 0.0
    crossings = s.tick(dt=3600.0, progress_signal=0.0)
    assert s.curiosity.value == 0.0
    assert not any(c.name == "curiosity" for c in crossings)


def test_progress_raises_curiosity_once():
    s = DriveSet()
    s.curiosity.value = 0.0
    count = 0
    for _ in range(1200):
        crossings = s.tick(dt=1.0, progress_signal=0.1)
        if any(c.name == "curiosity" for c in crossings):
            count += 1
    assert count == 1


def test_heterostatic_crossing_rearms_without_end_counts():
    d = Drive(name="i", heterostatic=True, value=0.9)
    assert d.consume_crossing() is True
    d.tick(3600.0, 0.0)
    assert d.own_ends == 0
    assert d.other_ends == 0
    assert d._has_fired is False
    assert d.consume_crossing() is False
    d.value = 0.9
    assert d.consume_crossing() is True


def test_homeostatic_crossing_counts_other_end():
    d = Drive(name="d", heterostatic=False, value=0.9)
    assert d.consume_crossing() is True
    d.tick(3600.0, 0.0)
    assert d.own_ends == 0
    assert d.other_ends == 1


def test_reset_deficits_preserves_curiosity():
    s = DriveSet()
    s.curiosity.value = 0.8
    s.curiosity.consume_crossing()
    s.boredom.value = 0.8
    s.boredom.consume_crossing()
    s.reset_deficits()
    assert s.curiosity.value == pytest.approx(0.8)
    assert s.curiosity._has_fired is True
    assert s.boredom.value == 0.0
    assert s.boredom._has_fired is False


def test_boredom_credit_for_learning_progress():
    ds = DriveSet()
    ds.boredom.value = ds.boredom.threshold
    ds.boredom.consume_crossing()
    ds.tick(
        60.0,
        progress_signal=0.0,
        activity_signal=0.0,
        boredom_no_response_signal=1.0,
    )
    assert (ds.boredom.own_ends, ds.boredom.other_ends) == (1, 0)

    ds2 = DriveSet()
    ds2.boredom.value = ds2.boredom.threshold
    ds2.boredom.consume_crossing()
    ds2.tick(
        60.0,
        progress_signal=0.0,
        activity_signal=0.0,
        boredom_no_response_signal=0.0,
    )
    assert (ds2.boredom.own_ends, ds2.boredom.other_ends) == (0, 1)

    ds3 = DriveSet()
    ds3.boredom.value = ds3.boredom.threshold
    ds3.boredom.consume_crossing()
    ds3.tick(60.0, progress_signal=0.0, activity_signal=0.0)
    assert (ds3.boredom.own_ends, ds3.boredom.other_ends) == (0, 1)


def test_from_config_keeps_curiosity_heterostatic():
    s = DriveSet.from_config({"curiosity": {"decay_rate": 0.002}})
    assert s.curiosity.heterostatic is True
    assert s.curiosity.decay_rate == pytest.approx(0.002)


def test_clear_active_for_drive_removes_only_matching_active_goals():
    ledger = GoalLedger()
    g1 = ledger.add("relieve curiosity", priority=0.5, drive="curiosity")
    ledger.add("relieve boredom", priority=0.5, drive="boredom")
    removed = ledger.clear_active_for_drive("curiosity")
    assert removed == [g1]
    assert ledger.active_for_drive("curiosity") is None
    assert ledger.active_for_drive("boredom") is not None
    assert ledger.outcome_counts() == (0, 0)
