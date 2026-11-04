# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
from __future__ import annotations

import numpy as np
import pytest

from kaine.workspace.content import ContentDecoder, ContentEncoder, ContentLevel


def test_encoder_decode_round_trip():
    enc = ContentEncoder(input_dim=8, code_dim=4)
    dec = ContentDecoder(code_dim=4, output_dim=8)
    rng = np.random.default_rng(42)
    x = rng.standard_normal(8)

    z = enc.encode(x)
    x_hat = dec.decode(z)
    init_err = float(np.mean((x - x_hat) ** 2))

    for _ in range(100):
        z = enc.encode(x)
        loss, grad_z = dec.adapt(z, x)
        enc.adapt(x, grad_z)

    z = enc.encode(x)
    x_hat = dec.decode(z)
    final_err = float(np.mean((x - x_hat) ** 2))
    assert final_err < init_err


def test_z_k_intensity_weighting():
    cl = ContentLevel({"vision": 4, "audition": 2}, code_dim=3)
    rng = np.random.default_rng(43)
    vis = rng.standard_normal(4)
    aud = rng.standard_normal(2)

    z_vis_only = cl.update_code(
        {"vision": vis, "audition": aud},
        {"vision": 1.0, "audition": 0.0},
    )
    expected = cl._encoders["vision"].encode(vis)
    np.testing.assert_allclose(z_vis_only, expected)

    z_equal = cl.update_code(
        {"vision": vis, "audition": aud},
        {"vision": 0.5, "audition": 0.5},
    )
    enc_vis = cl._encoders["vision"].encode(vis)
    enc_aud = cl._encoders["audition"].encode(aud)
    expected_mean = (enc_vis + enc_aud) / 2.0
    np.testing.assert_allclose(z_equal, expected_mean)


def test_training_reduces_loss():
    cl = ContentLevel({"vision": 8, "audition": 4}, code_dim=6)
    rng = np.random.default_rng(44)
    vis = rng.standard_normal(8)
    aud = rng.standard_normal(4)
    observed = {"vision": vis, "audition": aud}
    intensities = {"vision": 1.0, "audition": 1.0}

    cl.update_code(observed, intensities)
    first_losses = cl.train_step(observed)
    first_total = sum(first_losses.values())

    for _ in range(99):
        cl.update_code(observed, intensities)
        cl.train_step(observed)

    cl.update_code(observed, intensities)
    final_losses = cl.train_step(observed)
    final_total = sum(final_losses.values())
    assert final_total < first_total


def test_state_dict_round_trip():
    cl1 = ContentLevel({"vision": 5, "audition": 3}, code_dim=4)
    rng = np.random.default_rng(45)
    vis = rng.standard_normal(5)
    aud = rng.standard_normal(3)

    cl1.update_code({"vision": vis, "audition": aud}, {"vision": 0.7, "audition": 0.3})
    cl1.train_step({"vision": vis, "audition": aud})

    state = cl1.state_dict()
    cl2 = ContentLevel({"vision": 5, "audition": 3}, code_dim=4)
    cl2.load_state_dict(state)

    for proc in ["vision", "audition"]:
        pred1 = cl1.predict(proc)
        pred2 = cl2.predict(proc)
        assert pred1 is not None and pred2 is not None
        np.testing.assert_allclose(pred1, pred2)


def test_shape_mismatch_rejection():
    cl = ContentLevel({"vision": 8}, code_dim=4)
    state = cl.state_dict()
    state["encoders"]["vision"]["weights"] = np.zeros((10, 10)).tolist()
    with pytest.raises(ValueError, match="shape mismatch"):
        cl.load_state_dict(state)


def test_non_finite_rejection():
    cl = ContentLevel({"vision": 6}, code_dim=3)
    rng = np.random.default_rng(46)
    cl.update_code({"vision": rng.standard_normal(6)}, {"vision": 1.0})
    state = cl.state_dict()
    state["z_k"] = [float("inf")] * 3
    with pytest.raises(ValueError, match="non-finite"):
        cl.load_state_dict(state)


def test_predict_none_when_no_update():
    cl = ContentLevel({"vision": 7}, code_dim=5)
    assert cl.predict("vision") is None


def test_unknown_processor_predict():
    cl = ContentLevel({"vision": 7}, code_dim=5)
    assert cl.predict("nonexistent") is None


def test_code_dim_mismatch_rejection():
    cl = ContentLevel({"vision": 5, "audition": 2}, code_dim=4)
    state = cl.state_dict()
    state["code_dim"] = 8
    with pytest.raises(ValueError, match="code_dim mismatch"):
        cl.load_state_dict(state)


def test_extra_processor_in_state_skipped():
    cl = ContentLevel({"vision": 5}, code_dim=3)
    state = cl.state_dict()
    state["encoders"]["fake"] = {
        "weights": np.zeros((3, 3)).tolist(),
        "input_dim": 3,
        "code_dim": 3,
        "lr": 1e-3,
    }
    cl.load_state_dict(state)
