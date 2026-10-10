# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math

import pytest

from kaine.modules.intensity import graded_intensity


def test_graded_intensity_halfway():
    assert graded_intensity(0.2, 0.7, 1.0) == pytest.approx(0.45)


def test_graded_intensity_reaches_alert():
    assert graded_intensity(0.2, 0.7, 2.0) == pytest.approx(0.7)


def test_graded_intensity_saturates():
    assert graded_intensity(0.2, 0.7, 5.0) == pytest.approx(0.7)


def test_graded_intensity_non_finite_or_negative_returns_baseline():
    for ratio in (0.0, -1.0, math.nan, math.inf):
        assert graded_intensity(0.2, 0.7, ratio) == pytest.approx(0.2)
