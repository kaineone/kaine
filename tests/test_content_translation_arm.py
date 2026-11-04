# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
from __future__ import annotations

import numpy as np

from kaine.workspace.content import ContentLevel


def test_translation_loss_decreases():
    cl = ContentLevel({"vision": 8, "audition": 4}, code_dim=6)
    rng = np.random.default_rng(99)
    vis = rng.standard_normal(8)
    aud = rng.standard_normal(4)
    observed = {"vision": vis, "audition": aud}

    first = cl.train_step_translation(observed)
    first_total = sum(first.values())
    for _ in range(99):
        cl.train_step_translation(observed)
    final = cl.train_step_translation(observed)
    final_total = sum(final.values())
    assert final_total < first_total


def test_translation_different_from_prediction():
    rng = np.random.default_rng(100)
    vis = rng.standard_normal(8)
    aud = rng.standard_normal(4)
    observed = {"vision": vis, "audition": aud}
    intensities = {"vision": 1.0, "audition": 1.0}

    cl_pred = ContentLevel({"vision": 8, "audition": 4}, code_dim=6)
    cl_trans = ContentLevel({"vision": 8, "audition": 4}, code_dim=6)

    for _ in range(50):
        cl_pred.update_code(observed, intensities)
        cl_pred.train_step(observed)
        cl_trans.train_step_translation(observed)

    w_pred = cl_pred._encoders["vision"]._weights
    w_trans = cl_trans._encoders["vision"]._weights
    assert not np.allclose(w_pred, w_trans)
