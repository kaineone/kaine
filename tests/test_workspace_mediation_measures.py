# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the workspace-mediation ablation's pure measures and the
flat fan-in control snapshot (the fair-null conditioning path)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import validate_event
from kaine.evaluation.benchmarks.workspace_mediation_ablation.conditioning import (
    flat_fan_in_snapshot,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.measures import (
    entropy_fraction,
    mean_windowed_correlation,
    pearson,
    shannon_entropy,
    sign_test_pvalue,
    windowed_correlations,
)


def _ev(source: str, salience: float, text: str = "x"):
    return validate_event(
        source=source,
        type=f"{source}.report",
        payload={"text": text},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


# --------------------------- pearson --------------------------------------- #


def test_pearson_perfect_positive():
    assert pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)


def test_pearson_perfect_negative():
    assert pearson([1.0, 2.0, 3.0], [6.0, 4.0, 2.0]) == pytest.approx(-1.0)


def test_pearson_undefined_on_short_series():
    assert pearson([1.0], [2.0]) is None
    assert pearson([], []) is None


def test_pearson_undefined_on_constant_series():
    # A constant series has zero variance -> correlation is undefined (None),
    # NOT zero. This distinction guards against a false NULL.
    assert pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_pearson_clamped_to_unit_range():
    r = pearson([0.0, 1e-9, 2e-9, 3e-9], [0.0, 1e-9, 2e-9, 3e-9])
    assert r is not None and -1.0 <= r <= 1.0


# --------------------------- windowed correlation -------------------------- #


def test_windowed_correlations_skips_undefined_windows():
    # Second window [1,1] on xs is constant -> undefined and skipped.
    xs = [1.0, 2.0, 2.0, 2.0]
    ys = [1.0, 2.0, 3.0, 4.0]
    cors = windowed_correlations(xs, ys, window=2)
    # 3 windows total; those with a constant xs sub-window are skipped.
    assert all(-1.0 <= c <= 1.0 for c in cors)


def test_windowed_requires_min_window():
    with pytest.raises(ValueError):
        windowed_correlations([1.0, 2.0], [1.0, 2.0], window=1)


def test_mean_windowed_correlation_none_when_all_undefined():
    # Both series constant everywhere -> every window undefined -> None.
    assert mean_windowed_correlation([2.0] * 5, [3.0] * 5, window=3) is None


def test_mean_windowed_correlation_detects_coupling():
    # Coupled series should yield a high mean windowed correlation; independent
    # (anti-phase) series a lower one — the ablation's primary signature.
    coupled_a = [0.1, 0.5, 0.2, 0.7, 0.3, 0.8]
    coupled_b = [0.15, 0.55, 0.25, 0.72, 0.33, 0.83]
    anti_a = [0.1, 0.9, 0.1, 0.9, 0.1, 0.9]
    anti_b = [0.9, 0.1, 0.9, 0.1, 0.9, 0.1]
    m_coupled = mean_windowed_correlation(coupled_a, coupled_b, window=3)
    m_anti = mean_windowed_correlation(anti_a, anti_b, window=3)
    assert m_coupled is not None and m_anti is not None
    assert m_coupled > m_anti


# --------------------------- entropy --------------------------------------- #


def test_shannon_entropy_degenerate_is_zero():
    assert shannon_entropy(["soma", "soma", "soma"]) == pytest.approx(0.0)
    assert shannon_entropy([]) == pytest.approx(0.0)


def test_shannon_entropy_uniform_two_is_one_bit():
    assert shannon_entropy(["soma", "chronos"]) == pytest.approx(1.0)


def test_entropy_fraction_between_extremes():
    # A non-trivial, non-uniform selection sits strictly between 0 and 1.
    frac = entropy_fraction(["soma", "chronos", "soma", "soma", "chronos", "soma"])
    assert frac is not None and 0.0 < frac < 1.0


def test_entropy_fraction_none_for_single_source():
    assert entropy_fraction(["soma", "soma"]) is None
    assert entropy_fraction([]) is None


# --------------------------- sign-test p-value ----------------------------- #


def test_sign_test_all_positive_is_significant():
    # 5/5 positive -> p = (1/2)^5 = 0.03125 < 0.05.
    p = sign_test_pvalue([0.2, 0.1, 0.3, 0.15, 0.4])
    assert p == pytest.approx(1.0 / 32.0)
    assert p < 0.05


def test_sign_test_mixed_not_significant():
    p = sign_test_pvalue([0.2, -0.1, 0.3, -0.15, 0.4])
    assert p > 0.05


def test_sign_test_excludes_none_and_zero_ties():
    # Only the three positive/negative non-zero values count; two positives, one
    # negative -> upper tail P(X>=2) for n=3 = (3+1)/8 = 0.5.
    p = sign_test_pvalue([0.2, None, 0.0, 0.3, -0.1])
    assert p == pytest.approx(0.5)


def test_sign_test_empty_is_one():
    assert sign_test_pvalue([None, 0.0]) == pytest.approx(1.0)


# --------------------------- flat fan-in snapshot -------------------------- #


def test_flat_fan_in_retains_all_candidates_with_raw_salience():
    candidates = [
        ("e1", _ev("soma", 0.3)),
        ("e2", _ev("chronos", 0.7)),
        ("e3", _ev("audition", 0.9)),
    ]
    snap = flat_fan_in_snapshot(5, candidates, is_experiential=True)
    # No top-k truncation: every candidate is retained (not starved vs on-arm).
    assert len(snap.selected_events) == 3
    # Raw published salience is used as the score (not a competitive score).
    assert snap.salience_scores == {"e1": 0.3, "e2": 0.7, "e3": 0.9}
    # No threshold gate in the control.
    assert snap.inhibited is False
    assert snap.is_experiential is True
    assert snap.tick_index == 5
    assert snap.metadata["conditioning"] == "flat_fan_in"
    assert snap.metadata["candidate_count"] == 3


def test_flat_fan_in_empty_is_safe():
    snap = flat_fan_in_snapshot(0, [])
    assert snap.selected_events == []
    assert snap.salience_scores == {}
    assert snap.inhibited is False
