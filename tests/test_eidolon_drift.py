# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
from collections import Counter

import pytest

from kaine.modules.eidolon.drift import (
    DriftDetector,
    SourceDistributionDrift,
)


def _old_score(recent: Counter[str], cumulative: Counter[str], eps: float = 1e-3) -> float:
    """Smoothed symmetric KL as used by the old cumulative-as-reference formula."""
    if not recent or not cumulative:
        return 0.0
    all_keys = set(recent) | set(cumulative)
    rec_total = sum(recent.values())
    cum_total = sum(cumulative.values())
    score = 0.0
    for key in all_keys:
        p = (recent.get(key, 0) + eps) / (rec_total + eps * len(all_keys))
        q = (cumulative.get(key, 0) + eps) / (cum_total + eps * len(all_keys))
        score += p * math.log(p / q) + q * math.log(q / p)
    return score


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
    for _ in range(10):
        d.observe(["mnemos", "mnemos", "mnemos"])
    drifted = d.observe(["mnemos", "mnemos"])
    assert drifted.score > baseline.score


def test_top_drifted_sources_populated_after_observations():
    d = SourceDistributionDrift(window=4)
    for _ in range(8):
        d.observe(["a", "b"])
    r = d.observe(["c", "c", "c"])
    assert isinstance(r.top_drifted_sources, tuple)
    assert len(r.top_drifted_sources) > 0


def test_window_eviction():
    d = SourceDistributionDrift(window=4)
    for i in range(10):
        d.observe([f"src{i}"])
    r = d.observe(["last"])
    assert r.recent_count <= 4


def test_reset_clears_state():
    d = SourceDistributionDrift(window=4)
    for _ in range(5):
        d.observe(["a"])
    d.reset()
    assert d.recent_count == 0
    assert d.historical_count == 0
    assert d.reference_count == 0


def test_score_is_non_negative():
    d = SourceDistributionDrift(window=10)
    for _ in range(20):
        d.observe(["a", "b", "c"])
    r = d.observe(["x"])
    assert r.score >= 0


def test_recent_historical_and_reference_counts_consistent():
    d = SourceDistributionDrift(window=10)
    for _ in range(25):
        d.observe(["a", "b"])
    r = d.observe(["a"])
    assert r.historical_count == 51
    assert r.recent_count == 19
    assert r.reference_count == 32


def test_no_score_until_reference_fills_even_when_mix_changes():
    d = SourceDistributionDrift(window=10)
    for _ in range(10):
        d.observe(["a"])
    for _ in range(5):
        d.observe(["b"])
    r = d.observe(["b"])
    assert r.score == 0.0


def test_stable_mix_over_many_observations_low_drift():
    d = SourceDistributionDrift(window=20)
    for _ in range(60):
        d.observe(["a", "b"])
    r = d.observe(["a", "b"])
    assert r.score < 0.1


def test_new_score_is_at_least_old_cumulative_formula_score():
    d = SourceDistributionDrift(window=20, epsilon=1e-3)
    for _ in range(40):
        d.observe(["soma", "chronos"])
    for _ in range(20):
        d.observe(["mnemos", "mnemos", "soma"])
    r = d.observe(["mnemos", "mnemos", "soma"])

    recent_counter = Counter({"soma": 20, "mnemos": 40})
    cumulative_counter = Counter({"soma": 60, "chronos": 40, "mnemos": 40})
    old = _old_score(recent_counter, cumulative_counter, eps=1e-3)

    assert r.score >= old


def test_score_zero_until_reference_batches_reaches_window():
    d = SourceDistributionDrift(window=5)
    for _ in range(5):
        d.observe(["a"])
    for _ in range(3):
        d.observe(["b"])
    r = d.observe(["b"])
    assert r.score == 0.0
    assert r.reference_count == 4

    r2 = d.observe(["b"])
    assert r2.score > 0.0
    assert r2.reference_count == 5
