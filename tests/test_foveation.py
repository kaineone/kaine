# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Attention-driven foveation core: spatial saliency, fovea select, view derivation."""

from __future__ import annotations

import numpy as np
import pytest

from kaine.modules.topos.foveation import (
    FoveaPredictor,
    FoveaTarget,
    SpatialSaliency,
    arousal_to_size,
    combine_saliency,
    foveate,
    select_fovea,
)


def _frame(h=240, w=320, fill=0):
    return np.full((h, w, 3), fill, dtype=np.uint8)


# --------------------------------------------------------------------------- #
# spatial saliency
# --------------------------------------------------------------------------- #


def test_first_frame_has_no_change():
    sal = SpatialSaliency(grid=(6, 8))
    m = sal.observe(_frame())
    assert m.shape == (6, 8)
    assert float(m.max()) == 0.0


def test_localized_change_lights_that_tile():
    sal = SpatialSaliency(grid=(6, 8))
    sal.observe(_frame(fill=0))
    f = _frame(fill=0)
    # brighten a patch in the lower-right quadrant
    f[180:240, 260:320] = 255
    m = sal.observe(f)
    hottest = np.unravel_index(int(np.argmax(m)), m.shape)
    assert hottest[0] >= 3 and hottest[1] >= 5  # lower-right region


# --------------------------------------------------------------------------- #
# combine
# --------------------------------------------------------------------------- #


def test_combine_bottom_up_only():
    bu = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    out = combine_saliency(bu, None, w_bottom_up=2.0)
    assert np.allclose(out, bu * 2.0)


def test_top_down_bias_can_move_the_peak():
    bu = np.array([[0.0, 1.0], [0.0, 0.0]], dtype=np.float32)  # peak at (0,1)
    td = np.array([[0.0, 0.0], [5.0, 0.0]], dtype=np.float32)  # bias at (1,0)
    out = combine_saliency(bu, td, w_bottom_up=1.0, w_top_down=1.0)
    assert np.unravel_index(int(np.argmax(out)), out.shape) == (1, 0)


def test_combine_shape_mismatch_raises():
    with pytest.raises(ValueError):
        combine_saliency(np.zeros((2, 2)), np.zeros((3, 3)))


# --------------------------------------------------------------------------- #
# arousal -> size + select
# --------------------------------------------------------------------------- #


def test_arousal_narrows_the_fovea():
    lo, hi = 0.12, 0.5
    assert arousal_to_size(1.0, size_range=(lo, hi)) == pytest.approx(
        lo
    )  # high -> tight
    assert arousal_to_size(0.0, size_range=(lo, hi)) == pytest.approx(hi)  # low -> wide
    assert arousal_to_size(0.5, size_range=(lo, hi)) == pytest.approx((lo + hi) / 2)


def test_flat_saliency_targets_centre():
    t = select_fovea(np.zeros((6, 8), dtype=np.float32), arousal=0.0)
    assert t.x == pytest.approx(0.5) and t.y == pytest.approx(0.5)


def test_argmax_tile_becomes_the_target():
    sal = np.zeros((4, 4), dtype=np.float32)
    sal[3, 0] = 9.0  # bottom-left
    t = select_fovea(sal)
    assert t.x < 0.5 and t.y > 0.5


def test_hysteresis_holds_previous_between_comparable_tiles():
    prev = FoveaTarget(x=0.9, y=0.1, size=0.3)  # tile (row0, last col)
    sal = np.zeros((4, 4), dtype=np.float32)
    sal[0, 3] = 1.00  # prev's tile
    sal[3, 0] = 1.05  # a new tile, only 5% higher
    held = select_fovea(sal, prev=prev, hysteresis=0.10)  # needs >10% to switch
    assert held.x == pytest.approx(0.9) and held.y == pytest.approx(0.1)
    switched = select_fovea(sal, prev=prev, hysteresis=0.02)  # 2% threshold -> switch
    assert switched.x < 0.5 and switched.y > 0.5


# --------------------------------------------------------------------------- #
# foveate (view derivation)
# --------------------------------------------------------------------------- #


def test_peripheral_and_foveal_shapes():
    f = _frame(480, 640)
    peripheral, foveal = foveate(
        f,
        FoveaTarget(0.5, 0.5, 0.2),
        peripheral_size=(320, 180),
        foveal_size=(224, 224),
    )
    assert peripheral.shape == (180, 320, 3)
    assert foveal.shape == (224, 224, 3)


def test_foveal_crop_captures_the_targeted_region():
    f = _frame(480, 640, fill=0)
    # a bright block at the top-left; fovea there should see bright, centre should not
    f[0:120, 0:160] = 255
    _, foveal_tl = foveate(f, FoveaTarget(0.12, 0.12, 0.12), foveal_size=(64, 64))
    _, foveal_center = foveate(f, FoveaTarget(0.5, 0.5, 0.12), foveal_size=(64, 64))
    assert foveal_tl.mean() > foveal_center.mean()


def test_fovea_near_edge_is_clamped_not_crashing():
    f = _frame(200, 200)
    # target at the extreme corner with a large size — must clamp, not raise
    peripheral, foveal = foveate(f, FoveaTarget(1.0, 1.0, 0.9), foveal_size=(32, 32))
    assert foveal.shape == (32, 32, 3)


# --------------------------------------------------------------------------- #
# FoveaPredictor — attention schema (predicted next fovea)
# --------------------------------------------------------------------------- #


def test_first_prediction_is_the_current_target():
    # No prior trajectory → zero velocity → predict "stay put".
    p = FoveaPredictor()
    cur = FoveaTarget(0.4, 0.6, 0.2)
    pred = p.predict_next(cur)
    assert pred.x == pytest.approx(cur.x)
    assert pred.y == pytest.approx(cur.y)
    assert pred.size == pytest.approx(cur.size)


def test_constant_velocity_extrapolates_forward():
    # A steady rightward+downward drift should be extrapolated one step ahead.
    p = FoveaPredictor(momentum=0.0)  # no smoothing → pure last-delta velocity
    p.predict_next(FoveaTarget(0.10, 0.10, 0.30))
    p.predict_next(FoveaTarget(0.20, 0.25, 0.30))  # velocity (+0.10, +0.15, 0)
    pred = p.predict_next(FoveaTarget(0.30, 0.40, 0.30))
    assert pred.x == pytest.approx(0.40)
    assert pred.y == pytest.approx(0.55)
    assert pred.size == pytest.approx(0.30)


def test_prediction_is_clamped_to_unit_range():
    p = FoveaPredictor(momentum=0.0)
    p.predict_next(FoveaTarget(0.7, 0.5, 0.5))
    pred = p.predict_next(FoveaTarget(0.95, 0.5, 0.5))  # velocity +0.25 → 1.20
    assert pred.x == pytest.approx(1.0)  # clamped, not out of range
    assert 0.0 <= pred.y <= 1.0 and 0.0 <= pred.size <= 1.0


def test_prediction_is_content_free():
    # A predicted fovea is only normalized coordinates + size — never pixels.
    p = FoveaPredictor()
    d = p.predict_next(FoveaTarget(0.3, 0.7, 0.25)).to_dict()
    assert set(d) == {"x", "y", "size"}
    assert all(isinstance(v, float) for v in d.values())


def test_momentum_must_be_in_unit_range():
    with pytest.raises(ValueError):
        FoveaPredictor(momentum=1.5)
