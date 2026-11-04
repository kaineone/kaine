# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
from __future__ import annotations

from kaine.modules.feedback import blend_weights_3


def test_3way_blend_known_precisions():
    w = blend_weights_3(0.5, 0.3, 0.4)
    assert abs(sum(w) - 1.0) < 1e-10
    assert w[1] > w[2] > w[0]


def test_content_none_falls_back_to_2way():
    w = blend_weights_3(0.5, 0.3, None)
    assert w[2] == 0.0
    assert abs(sum(w) - 1.0) < 1e-10
    assert w[1] > w[0]


def test_top_none_2way_own_content():
    w = blend_weights_3(0.5, None, 0.4)
    assert w[1] == 0.0
    assert abs(sum(w) - 1.0) < 1e-10
    assert w[2] > w[0]


def test_both_none_all_own():
    assert blend_weights_3(0.5, None, None) == (1.0, 0.0, 0.0)


def test_own_zero_splits_among_available():
    w = blend_weights_3(0.0, 0.3, 0.4)
    assert w[0] == 0.0
    assert abs(sum(w) - 1.0) < 1e-10
    assert w[1] > w[2]


def test_blend_state_includes_content_errors():
    blend = _make_blend()
    sd = blend.state_dict()
    assert "content_errors" in sd


def _make_blend():
    from kaine.modules.feedback import TopDownBlend

    class FakeInner:
        _last_prediction = None
        _last_null_prediction = None
        last_scored_had_context = False
        last_error_defined = True
        last_reading_skipped = False
        last_null_error = None
        context_dim = 24
        suspended = False

        def step(self, feature, **kw):
            self._last_prediction = list(feature)
            return 0.1

        def state_dict(self):
            return {}

        def load_state_dict(self, s):
            pass

    return TopDownBlend(FakeInner())
