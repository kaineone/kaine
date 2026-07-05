# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for SubstrateForwardModel (soma/forward.py) — CfC-backed (via ncps)."""
from __future__ import annotations

import math

import pytest

from kaine.modules.soma.forward import (
    DEFAULT_FEATURE_DIM,
    SubstrateForwardModel,
    metrics_to_feature_vector,
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_construction_default_dims():
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel()
    assert m.feature_dim == DEFAULT_FEATURE_DIM
    assert m.units == 32
    assert m.suspended is False
    assert m.device == "cpu"


def test_construction_custom_dims():
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=16)
    assert m.feature_dim == 4
    assert m.units == 16


def test_construction_rejects_invalid():
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    with pytest.raises(ValueError):
        SubstrateForwardModel(feature_dim=0)
    with pytest.raises(ValueError):
        SubstrateForwardModel(units=0)
    with pytest.raises(ValueError):
        SubstrateForwardModel(lr=0.0)


def test_force_cuda_ignored_soma_forward_stays_on_cpu(monkeypatch):
    """CPU-only by policy, mirroring Chronos's CfCNetwork pin."""
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    monkeypatch.setenv("KAINE_FORCE_DEVICE", "cuda")
    m = SubstrateForwardModel(feature_dim=4, units=8)
    assert m.device == "cpu"


# ---------------------------------------------------------------------------
# It's actually a CfC (ncps-backed reservoir + linear readout)
# ---------------------------------------------------------------------------

def test_is_ncps_cfc_backed():
    """The reservoir must be a real ncps CfC, not a hand-rolled MLP."""
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    from ncps.torch import CfC

    m = SubstrateForwardModel(feature_dim=4, units=8, seed=0)
    assert isinstance(m._cfc, CfC)
    # The reservoir is frozen — it never trains.
    assert all(not p.requires_grad for p in m._cfc.parameters())
    # Only the linear readout adapts online.
    assert all(p.requires_grad for p in m._readout.parameters())


# ---------------------------------------------------------------------------
# predict()
# ---------------------------------------------------------------------------

def test_predict_returns_correct_shape():
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=42)
    out = m.predict([0.1, 0.2, 0.3, 0.4])
    assert len(out) == 4
    assert all(math.isfinite(v) for v in out)


def test_predict_does_not_mutate_recurrent_state():
    """predict() is a side-effect-free peek; step() advances state."""
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=42)
    m.predict([0.1, 0.2, 0.3, 0.4])
    assert m._hx is None
    m.predict([0.9, 0.9, 0.9, 0.9])
    assert m._hx is None


def test_predict_rejects_wrong_dim():
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8)
    with pytest.raises(ValueError):
        m.predict([0.1, 0.2])


# ---------------------------------------------------------------------------
# step() — first tick returns 0.0
# ---------------------------------------------------------------------------

def test_first_step_returns_zero_error():
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=42)
    err = m.step([0.1, 0.2, 0.3, 0.4])
    assert err == 0.0


def test_second_step_returns_finite_error():
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=42)
    m.step([0.1, 0.2, 0.3, 0.4])
    err = m.step([0.2, 0.3, 0.4, 0.5])
    assert math.isfinite(err)
    assert err >= 0.0


def test_step_advances_recurrent_state():
    """Unlike predict(), step() commits the CfC hidden state forward."""
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=0)
    assert m._hx is None
    m.step([0.1, 0.2, 0.3, 0.4])
    assert m._hx is not None


# ---------------------------------------------------------------------------
# Online adaptation reduces error on a stationary signal
# ---------------------------------------------------------------------------

def test_online_adaptation_reduces_error_on_stationary_signal():
    """After many ticks on a fixed vector, prediction error should shrink."""
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=0)
    feature = [0.5, 0.3, 0.2, 0.1]
    errors = []
    for _ in range(60):
        err = m.step(feature)
        errors.append(err)
    # Allow warm-up; compare last quarter against first quarter (post-warm-up).
    early = errors[5:15]
    late = errors[45:60]
    if early and late:
        assert sum(late) / len(late) < sum(early) / len(early), (
            f"expected late mean {sum(late)/len(late):.4f} < "
            f"early mean {sum(early)/len(early):.4f}"
        )


def test_adaptation_changes_readout_weights():
    """step() must actually move the readout's weights over time."""
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=0)
    feature = [0.5, 0.3, 0.2, 0.1]
    before = m.state_dict()
    for _ in range(20):
        m.step(feature)
    after = m.state_dict()
    changed = any(
        b_row != a_row
        for b_row, a_row in zip(before["weight"], after["weight"])
    ) or before["bias"] != after["bias"]
    assert changed, "expected online adaptation to move readout weights"


# ---------------------------------------------------------------------------
# Non-finite guard — corrupted/glitched sensor read scenario
# ---------------------------------------------------------------------------

def test_nonfinite_loss_skips_update():
    """When we inject a non-finite feature, the model must not crash."""
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=0)
    # Warm up with clean data to get a non-None last_prediction.
    m.step([0.1, 0.2, 0.3, 0.4])
    # Capture weight snapshot before the bad step.
    before = m.state_dict()
    # Inject non-finite input — the model should survive.
    try:
        err = m.step([float("inf"), float("nan"), 0.0, 0.0])
    except Exception as exc:
        pytest.fail(f"model raised on non-finite input: {exc}")
    assert err == 0.0
    # Weights should be identical to before (guard fired, no update).
    after = m.state_dict()
    assert before["weight"] == after["weight"]
    assert before["bias"] == after["bias"]


def test_nonfinite_input_does_not_corrupt_recurrent_state():
    """A non-finite feature must not be committed into the CfC hidden state."""
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=0)
    m.step([0.1, 0.2, 0.3, 0.4])
    hx_before = m._hx
    m.step([float("inf"), float("nan"), 0.0, 0.0])
    assert m._hx is hx_before
    # Subsequent clean ticks must still produce finite predictions.
    err = m.step([0.2, 0.2, 0.2, 0.2])
    assert math.isfinite(err)


# ---------------------------------------------------------------------------
# suspended flag freezes weights
# ---------------------------------------------------------------------------

def test_suspended_flag_freezes_weights():
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=1)
    feature = [0.5, 0.4, 0.3, 0.2]
    # Warm up.
    m.step(feature)
    before = m.state_dict()
    m.suspended = True
    for _ in range(20):
        m.step(feature)
    after = m.state_dict()
    assert before["weight"] == after["weight"]
    assert before["bias"] == after["bias"]


def test_suspended_flag_still_advances_recurrent_state():
    """Suspending freezes the readout's weights, not the CfC's recurrent tick."""
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=1)
    feature = [0.5, 0.4, 0.3, 0.2]
    m.step(feature)
    m.suspended = True
    hx_before = m._hx
    m.step(feature)
    assert m._hx is not hx_before


# ---------------------------------------------------------------------------
# Serialisation roundtrip
# ---------------------------------------------------------------------------

def test_state_dict_roundtrip():
    """After loading weights, a fresh model with reset recurrent state must
    produce the same prediction as the original model with reset state.

    The CfC hidden state is ephemeral and not persisted, so we compare
    predictions after both models' recurrent state has been reset (the
    all-zero starting context).
    """
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8, seed=42)
    for _ in range(5):
        m.step([0.1, 0.2, 0.3, 0.4])
    sd = m.state_dict()

    # Reset m's recurrent state so both start from the same all-zero context.
    # NOTE: the two models still have DIFFERENT (independently seeded) frozen
    # CfC reservoirs, since the reservoir itself is never serialised (like
    # Chronos's CfCNetwork) — only the readout is. So this roundtrip checks
    # readout-weight fidelity, not bit-identical reservoirs.
    m.reset()
    pred1 = m.predict([0.5, 0.5, 0.5, 0.5])

    # Build a THIRD model with the SAME seed as m1's reservoir to confirm the
    # readout weights alone reproduce predictions when reservoirs match.
    m3 = SubstrateForwardModel(feature_dim=4, units=8, seed=42)
    m3.load_state_dict(sd)
    pred3 = m3.predict([0.5, 0.5, 0.5, 0.5])
    for a, b in zip(pred1, pred3):
        assert abs(a - b) < 1e-5


def test_state_dict_contains_no_raw_buffers():
    """state_dict must contain only weight+bias, never raw feature/hidden data."""
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8)
    for _ in range(5):
        m.step([0.3, 0.5, 0.2, 0.1])
    sd = m.state_dict()
    assert set(sd.keys()) == {"weight", "bias"}
    assert len(sd["weight"]) == 4  # feature_dim rows
    assert len(sd["weight"][0]) == 8  # units columns
    assert len(sd["bias"]) == 4


# ---------------------------------------------------------------------------
# prediction_error_to_salience
# ---------------------------------------------------------------------------

def test_salience_baseline_on_zero_error():
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8)
    s = m.prediction_error_to_salience(0.0, 0.1, 0.7)
    assert abs(s - 0.1) < 1e-6


def test_salience_in_range():
    pytest.importorskip("torch")
    pytest.importorskip("ncps")
    m = SubstrateForwardModel(feature_dim=4, units=8)
    for err in [0.0, 0.5, 1.0, 5.0]:
        s = m.prediction_error_to_salience(err, 0.1, 0.7)
        assert 0.1 <= s <= 0.7


# ---------------------------------------------------------------------------
# metrics_to_feature_vector helper
# ---------------------------------------------------------------------------

def test_metrics_to_feature_vector_known_keys():
    vec = metrics_to_feature_vector(
        {"cpu_percent": 50.0, "ram_percent": 80.0, "cycle_latency_avg_ms": 300.0},
        feature_dim=4,
        cycle_latency_target_ms=300.0,
    )
    assert len(vec) == 4
    assert abs(vec[0] - 0.5) < 1e-6   # cpu 50%
    assert abs(vec[1] - 0.8) < 1e-6   # ram 80%
    assert abs(vec[2] - 0.5) < 1e-6   # latency at 2x target = 0.5 clamped
    assert vec[3] == 0.0               # no gpu_*_temp_c key present


def test_metrics_to_feature_vector_missing_keys():
    vec = metrics_to_feature_vector({}, feature_dim=4)
    assert vec == [0.0, 0.0, 0.0, 0.0]


def test_metrics_to_feature_vector_clamped():
    vec = metrics_to_feature_vector(
        {"cpu_percent": 200.0, "ram_percent": -10.0},
        feature_dim=3,
    )
    assert vec[0] == 1.0
    assert vec[1] == 0.0


def test_metrics_to_feature_vector_gpu_temp_single():
    vec = metrics_to_feature_vector(
        {"gpu_0_temp_c": 75.0},
        feature_dim=4,
        gpu_temp_max_c=100.0,
    )
    assert abs(vec[3] - 0.75) < 1e-6


def test_metrics_to_feature_vector_gpu_temp_multi_uses_hottest():
    vec = metrics_to_feature_vector(
        {"gpu_0_temp_c": 60.0, "gpu_1_temp_c": 85.0},
        feature_dim=4,
        gpu_temp_max_c=100.0,
    )
    assert abs(vec[3] - 0.85) < 1e-6


def test_metrics_to_feature_vector_gpu_temp_truncated_when_dim_too_small():
    # feature_dim=3 truncates away the GPU slot entirely; must not raise.
    vec = metrics_to_feature_vector(
        {"gpu_0_temp_c": 90.0},
        feature_dim=3,
    )
    assert len(vec) == 3
