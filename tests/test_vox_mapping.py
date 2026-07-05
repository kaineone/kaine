# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.vox.mapping import (
    ChatterboxParams,
    affect_to_chatterbox,
)
from kaine.modules.thymos.state import DimensionalState


def test_baseline_returns_baseline_params():
    """With the default DimensionalState, baseline params come through."""
    p = affect_to_chatterbox(
        DimensionalState(),
        baseline_temperature=0.65,
        baseline_exaggeration=0.55,
        baseline_cfg_weight=0.4,
    )
    assert p.temperature == 0.65
    assert p.exaggeration == 0.55
    assert p.cfg_weight == 0.4
    assert p.speed_factor == 1.0


def test_higher_arousal_strictly_increases_exaggeration():
    low = affect_to_chatterbox(DimensionalState(valence=0.0, arousal=0.2))
    high = affect_to_chatterbox(DimensionalState(valence=0.0, arousal=0.8))
    assert high.exaggeration > low.exaggeration


def test_higher_arousal_strictly_increases_temperature():
    low = affect_to_chatterbox(DimensionalState(valence=0.0, arousal=0.2))
    high = affect_to_chatterbox(DimensionalState(valence=0.0, arousal=0.8))
    assert high.temperature > low.temperature


def test_stronger_valence_strictly_increases_cfg_weight():
    weak = affect_to_chatterbox(DimensionalState(valence=0.1, arousal=0.5))
    strong = affect_to_chatterbox(DimensionalState(valence=-0.9, arousal=0.5))
    assert strong.cfg_weight > weak.cfg_weight


def test_positive_valence_speeds_up():
    p = affect_to_chatterbox(DimensionalState(valence=0.9, arousal=0.5))
    assert p.speed_factor > 1.0


def test_negative_valence_slows_down():
    p = affect_to_chatterbox(DimensionalState(valence=-0.9, arousal=0.5))
    assert p.speed_factor < 1.0


def test_all_params_in_documented_bands():
    for v in (-1.0, -0.5, 0.0, 0.5, 1.0):
        for a in (0.0, 0.25, 0.5, 0.75, 1.0):
            p = affect_to_chatterbox(DimensionalState(valence=v, arousal=a))
            assert 0.4 <= p.temperature <= 0.95
            assert 0.3 <= p.exaggeration <= 0.95
            assert 0.3 <= p.cfg_weight <= 0.95
            assert 0.85 <= p.speed_factor <= 1.15


def test_to_request_kwargs_returns_floats():
    p = affect_to_chatterbox(DimensionalState(valence=0.5, arousal=0.5))
    kwargs = p.to_request_kwargs()
    assert set(kwargs.keys()) == {"temperature", "exaggeration", "cfg_weight", "speed_factor"}
    for v in kwargs.values():
        assert isinstance(v, float)
