# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.topos.habituation import (
    RollingMeanHabituator,
    SceneHabituator,
)


def test_protocol_runtime_checkable():
    assert isinstance(RollingMeanHabituator(), SceneHabituator)


def test_invalid_window_rejected():
    with pytest.raises(ValueError):
        RollingMeanHabituator(window=1)
    with pytest.raises(ValueError):
        RollingMeanHabituator(window=0)


def test_first_frame_is_fully_habituated():
    hab = RollingMeanHabituator(window=8)
    assert hab.observe([1.0, 2.0, 3.0]) == 1.0


def test_identical_frames_yield_high_habituation():
    hab = RollingMeanHabituator(window=16)
    for _ in range(8):
        score = hab.observe([0.5, 0.5, 0.5])
    assert score >= 0.9


def test_orthogonal_frames_yield_low_habituation():
    hab = RollingMeanHabituator(window=16)
    # 8 mutually orthogonal-ish frames
    frames = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0, 0.0],
        [0.0, 0.0, 0.0, -1.0],
    ]
    scores = [hab.observe(f) for f in frames]
    assert scores[-1] <= 0.5


def test_window_eviction_restores_responsiveness():
    hab = RollingMeanHabituator(window=4)
    for _ in range(4):
        hab.observe([1.0, 0.0])
    # window now full of identical frames → habituation high
    assert hab.observe([1.0, 0.0]) >= 0.9
    # introduce variance, then evict
    hab.observe([1.0, 5.0])
    hab.observe([1.0, -5.0])
    hab.observe([1.0, 5.0])
    score_varied = hab.observe([1.0, -5.0])
    assert score_varied < 0.5


def test_reset_clears_state():
    hab = RollingMeanHabituator(window=4)
    hab.observe([1.0, 0.0])
    hab.observe([0.0, 1.0])
    hab.reset()
    assert hab.observe([1.0, 0.0]) == 1.0
