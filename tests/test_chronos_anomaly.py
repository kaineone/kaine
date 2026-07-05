# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.chronos.anomaly import AnomalyDetector, RollingZScoreAnomaly


def test_protocol_runtime_checkable():
    assert isinstance(RollingZScoreAnomaly(), AnomalyDetector)


def test_invalid_window_rejected():
    with pytest.raises(ValueError):
        RollingZScoreAnomaly(window=1)


def test_empty_history_returns_zero():
    det = RollingZScoreAnomaly(window=4)
    assert det.observe([1.0, 0.0, 0.0]) == 0.0


def test_one_prior_sample_still_zero():
    det = RollingZScoreAnomaly(window=4)
    det.observe([1.0])
    assert det.observe([1.0]) == 0.0  # std is undefined with n=1 prior


def test_outlier_produces_large_score():
    det = RollingZScoreAnomaly(window=32)
    # Establish a low-variance baseline at norm ≈ 1.0
    for _ in range(20):
        det.observe([1.0])
    score = det.observe([3.0, 0.0, 0.0])  # norm 3.0
    assert score > 5.0


def test_score_is_non_negative():
    det = RollingZScoreAnomaly(window=8)
    for _ in range(4):
        det.observe([2.0, 0.0])
    score_low = det.observe([0.5, 0.5])
    assert score_low >= 0.0


def test_window_capacity_property():
    det = RollingZScoreAnomaly(window=16)
    assert det.window == 16
