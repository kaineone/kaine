# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.workspace.novelty import NoveltyTracker, fingerprint


def _ev(payload=None, source="soma", etype="t") -> Event:
    return Event(
        source=source,
        type=etype,
        payload=payload or {"x": 1},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def test_invalid_window_rejected():
    with pytest.raises(ValueError):
        NoveltyTracker(window=0)
    with pytest.raises(ValueError):
        NoveltyTracker(window=-1)


def test_first_observation_is_fully_novel():
    nt = NoveltyTracker(window=32)
    assert nt.observe(_ev()) == 1.0


def test_repeated_observation_reduces_novelty():
    nt = NoveltyTracker(window=32)
    same = _ev(payload={"x": 1})
    first = nt.observe(same)
    later = nt.observe(_ev(payload={"x": 1}))
    much_later_scores = [nt.observe(_ev(payload={"x": 1})) for _ in range(8)]
    assert first == 1.0
    assert later < first
    assert min(much_later_scores) < later


def test_window_eviction_restores_novelty():
    nt = NoveltyTracker(window=4)
    target = _ev(payload={"x": 1})
    nt.observe(target)
    for i in range(4):
        nt.observe(_ev(payload={"y": i}))
    # The original fingerprint has been evicted from the window.
    assert nt.observe(target) == 1.0


def test_fingerprint_distinct_for_distinct_events():
    a = _ev(payload={"x": 1})
    b = _ev(payload={"x": 2})
    assert fingerprint(a) != fingerprint(b)


def test_fingerprint_stable_under_dict_ordering():
    a = Event(
        source="soma",
        type="t",
        payload={"a": 1, "b": 2},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    b = Event(
        source="soma",
        type="t",
        payload={"b": 2, "a": 1},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    assert fingerprint(a) == fingerprint(b)


def test_reset_clears_window():
    nt = NoveltyTracker(window=8)
    nt.observe(_ev(payload={"x": 1}))
    nt.reset()
    assert nt.observe(_ev(payload={"x": 1})) == 1.0
