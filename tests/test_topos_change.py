# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.topos.change import (
    ChangeDetector,
    CosineChangeDetector,
    cosine_similarity,
)


def test_protocol_runtime_checkable():
    assert isinstance(CosineChangeDetector(), ChangeDetector)


def test_first_observation_zero():
    det = CosineChangeDetector()
    assert det.observe([1.0, 0.0, 0.0]) == 0.0


def test_identical_consecutive_frames_zero_change():
    det = CosineChangeDetector()
    det.observe([0.5, 0.5, 0.5])
    assert det.observe([0.5, 0.5, 0.5]) == pytest.approx(0.0, abs=1e-9)


def test_orthogonal_frames_change_one():
    det = CosineChangeDetector()
    det.observe([1.0, 0.0])
    assert det.observe([0.0, 1.0]) == pytest.approx(1.0, abs=1e-9)


def test_anti_correlated_frames_change_two():
    det = CosineChangeDetector()
    det.observe([1.0, 0.0])
    assert det.observe([-1.0, 0.0]) == pytest.approx(2.0, abs=1e-9)


def test_reset_clears_previous():
    det = CosineChangeDetector()
    det.observe([1.0, 0.0])
    det.reset()
    assert det.observe([0.0, 1.0]) == 0.0


def test_zero_vector_input_safe():
    det = CosineChangeDetector()
    det.observe([0.0, 0.0])
    # cosine of zero-vector returns 0.0 sim → change 1.0
    assert det.observe([1.0, 0.0]) == 1.0


def test_cosine_similarity_basic():
    assert cosine_similarity([1, 0], [1, 0]) == 1.0
    assert cosine_similarity([1, 0], [-1, 0]) == -1.0
    assert cosine_similarity([1, 0], [0, 1]) == 0.0
    assert cosine_similarity([0, 0], [1, 0]) == 0.0
