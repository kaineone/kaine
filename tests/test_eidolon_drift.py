# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.eidolon.drift import (
    DriftDetector,
    DriftResult,
    SourceDistributionDrift,
)


def test_protocol_runtime_checkable():
    assert isinstance(SourceDistributionDrift(), DriftDetector)


def test_invalid_window_rejected():
    with pytest.raises(ValueError):
        SourceDistributionDrift(window=0)
    with pytest.raises(ValueError):
        SourceDistributionDrift(epsilon=0)


def test_empty_state_yields_zero_drift():
    d = SourceDistributionDrift()
    r = d.observe([])
    assert r.score == 0.0


def test_stable_distribution_low_drift():
    d = SourceDistributionDrift(window=20)
    for _ in range(40):
        d.observe(["soma", "chronos", "topos"])
    r = d.observe(["soma", "chronos", "topos"])
    assert r.score < 0.1


def test_novel_source_increases_drift():
    d = SourceDistributionDrift(window=20)
    for _ in range(40):
        d.observe(["soma", "chronos"])
    baseline = d.observe(["soma", "chronos"])
    # Introduce a brand-new source heavily in recent window
    for _ in range(10):
        d.observe(["mnemos", "mnemos", "mnemos"])
    drifted = d.observe(["mnemos", "mnemos"])
    assert drifted.score > baseline.score


def test_top_drifted_sources_populated_after_observations():
    d = SourceDistributionDrift(window=4)
    for _ in range(5):
        d.observe(["a", "b"])
    r = d.observe(["c", "c", "c"])
    assert isinstance(r.top_drifted_sources, tuple)
    assert len(r.top_drifted_sources) > 0


def test_window_eviction():
    d = SourceDistributionDrift(window=4)
    for i in range(10):
        d.observe([f"src{i}"])
    # Only the last 4 batches contribute to recent_count.
    r = d.observe(["last"])
    assert r.recent_count <= 5  # 4 prior + 1 just-observed


def test_reset_clears_state():
    d = SourceDistributionDrift(window=4)
    for _ in range(5):
        d.observe(["a"])
    d.reset()
    assert d.recent_count == 0
    assert d.historical_count == 0


def test_score_is_non_negative():
    d = SourceDistributionDrift(window=10)
    for _ in range(20):
        d.observe(["a", "b", "c"])
    r = d.observe(["x"])
    assert r.score >= 0


def test_recent_count_and_historical_count_grow_consistently():
    d = SourceDistributionDrift(window=100)
    for _ in range(10):
        d.observe(["a", "b"])
    r = d.observe(["a"])
    # historical = 10 * 2 + 1 = 21; recent equals same since window holds all 11 batches
    assert r.historical_count == 21
    assert r.recent_count == 21
