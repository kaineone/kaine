# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.hypnos.scheduler import RestScheduler


def test_invalid_construction():
    with pytest.raises(ValueError):
        RestScheduler(interval_seconds=0, max_deferral_seconds=10)
    with pytest.raises(ValueError):
        RestScheduler(interval_seconds=1, max_deferral_seconds=-1)
    with pytest.raises(ValueError):
        RestScheduler(interval_seconds=1, max_deferral_seconds=10, per_defer_seconds=0)


def test_not_due_before_interval():
    now = [0.0]
    s = RestScheduler(
        interval_seconds=100, max_deferral_seconds=0, clock=lambda: now[0]
    )
    now[0] = 50.0
    assert s.is_due() is False


def test_due_after_interval():
    now = [0.0]
    s = RestScheduler(
        interval_seconds=100, max_deferral_seconds=0, clock=lambda: now[0]
    )
    now[0] = 101.0
    assert s.is_due() is True


def test_defer_within_window():
    now = [0.0]
    s = RestScheduler(
        interval_seconds=100,
        max_deferral_seconds=300,
        per_defer_seconds=60,
        clock=lambda: now[0],
    )
    now[0] = 101.0  # due
    assert s.is_due() is True
    assert s.try_defer() is True
    assert s.total_deferral == pytest.approx(60.0)
    now[0] = 110.0
    assert s.is_due() is False  # pushed back


def test_defer_refused_past_window():
    now = [0.0]
    s = RestScheduler(
        interval_seconds=100,
        max_deferral_seconds=100,
        per_defer_seconds=60,
        clock=lambda: now[0],
    )
    now[0] = 101.0
    assert s.try_defer() is True
    # Total deferral so far: 60. Max 100. So one more defer caps it.
    assert s.try_defer() is True
    assert s.total_deferral == pytest.approx(100.0)
    # Now any further defer is refused.
    assert s.try_defer() is False


def test_due_past_max_deferral_regardless_of_calls():
    now = [0.0]
    s = RestScheduler(
        interval_seconds=10,
        max_deferral_seconds=20,
        per_defer_seconds=5,
        clock=lambda: now[0],
    )
    now[0] = 11.0
    s.try_defer()  # effective due 16
    now[0] = 31.0  # past original_due_at + max_deferral = 10 + 20 = 30
    assert s.is_due() is True
    # And further defers are refused.
    assert s.try_defer() is False


def test_mark_completed_resets():
    now = [0.0]
    s = RestScheduler(
        interval_seconds=100,
        max_deferral_seconds=200,
        per_defer_seconds=60,
        clock=lambda: now[0],
    )
    now[0] = 105.0
    s.try_defer()
    s.mark_completed()
    # New deadline at now + interval.
    assert s.original_due_at == pytest.approx(205.0)
    assert s.effective_due_at == s.original_due_at
    assert s.is_due() is False
