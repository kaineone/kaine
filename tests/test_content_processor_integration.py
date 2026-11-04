# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
from __future__ import annotations

import numpy as np

from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.feedback import (
    FEEDBACK_KEY,
    FeedbackChannel,
    TopDownBlend,
)


def _make_snapshot(
    processor: str,
    content_prediction: list[float] | None = None,
    gain: float = 1.0,
    seq: list[float] | None = None,
) -> WorkspaceSnapshot:
    fb: dict = {
        "gains": {processor: gain},
        "sequence_prediction": seq,
        "episodes": [],
    }
    if content_prediction is not None:
        fb["content"] = {
            "predictions": {processor: content_prediction},
            "losses": {processor: 0.1},
            "z_k": [0.0] * 4,
        }
    return WorkspaceSnapshot(
        tick_index=1,
        selected_events=[],
        inhibited=False,
        salience_scores={},
        metadata={FEEDBACK_KEY: fb},
    )


class FakeForwardModel:
    context_dim = 0
    last_reading_skipped = False
    last_error_defined = True
    last_null_error = None
    last_scored_had_context = False
    suspended = False
    _last_prediction: list[float] | None = None
    _last_null_prediction: list[float] | None = None

    def __init__(self, dim: int):
        self._dim = dim

    def step(self, feature, **kw) -> float:
        self._last_prediction = [float(v) + 0.01 for v in feature]
        return 0.1


def test_feedback_channel_extracts_content_prediction():
    ch = FeedbackChannel("vision")
    snap = _make_snapshot("vision", content_prediction=[0.1, 0.2, 0.3])
    assert ch.observe(snap)
    assert ch.content_prediction == [0.1, 0.2, 0.3]


def test_feedback_channel_no_content_gives_none():
    ch = FeedbackChannel("vision")
    snap = _make_snapshot("vision", content_prediction=None)
    assert ch.observe(snap)
    assert ch.content_prediction is None


def test_blend_uses_content_prediction():
    inner = FakeForwardModel(4)
    blend = TopDownBlend(inner)

    rng = np.random.default_rng(42)
    feature = rng.standard_normal(4).tolist()

    blend.step(feature)
    cpred = [0.5, 0.5, 0.5, 0.5]
    blend.step(feature, content_prediction=cpred)
    err = blend.step(feature, content_prediction=cpred)
    assert isinstance(err, float)
    assert blend.last_content_error is not None


def test_blend_without_content_has_no_content_error():
    inner = FakeForwardModel(4)
    blend = TopDownBlend(inner)

    rng = np.random.default_rng(42)
    feature = rng.standard_normal(4).tolist()

    blend.step(feature)
    blend.step(feature)
    assert blend.last_content_error is None


def test_content_off_matches_content_absent():
    """With content_prediction=None, blend weights use 2-way not 3-way."""
    inner = FakeForwardModel(4)
    blend = TopDownBlend(inner)

    rng = np.random.default_rng(42)
    features = [rng.standard_normal(4).tolist() for _ in range(5)]

    errors_no_content = []
    for f in features:
        errors_no_content.append(blend.step(f))

    inner2 = FakeForwardModel(4)
    blend2 = TopDownBlend(inner2)

    errors_none_content = []
    for f in features:
        errors_none_content.append(blend2.step(f, content_prediction=None))

    assert errors_no_content == errors_none_content


def test_each_processor_channel_receives_own_prediction():
    vis_ch = FeedbackChannel("vision")
    aud_ch = FeedbackChannel("audition")

    fb = {
        "gains": {"vision": 1.0, "audition": 1.0},
        "sequence_prediction": None,
        "episodes": [],
        "content": {
            "predictions": {
                "vision": [0.1, 0.2],
                "audition": [0.3, 0.4, 0.5],
            },
            "losses": {"vision": 0.05, "audition": 0.08},
            "z_k": [0.0] * 4,
        },
    }
    snap = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[],
        inhibited=False,
        salience_scores={},
        metadata={FEEDBACK_KEY: fb},
    )

    vis_ch.observe(snap)
    aud_ch.observe(snap)

    assert vis_ch.content_prediction == [0.1, 0.2]
    assert aud_ch.content_prediction == [0.3, 0.4, 0.5]
