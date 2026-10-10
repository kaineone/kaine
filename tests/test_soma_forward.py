# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for SubstrateForwardModel (soma/forward.py) — CfC-backed."""
from __future__ import annotations

import importlib.util
import math

import pytest

from kaine.modules.soma.forward import (
    DEFAULT_FEATURE_DIM,
    SubstrateForwardModel,
    metrics_to_feature_vector,
)

_TORCH = (
    importlib.util.find_spec("torch") is not None
    and importlib.util.find_spec("ncps") is not None
)


def pytest_generate_tests(metafunc):
    if "backend" in metafunc.fixturenames:
        marks = [pytest.mark.skipif(not _TORCH, reason="torch/ncps not installed")]
        metafunc.parametrize(
            "backend",
            ["numpy", pytest.param("torch", marks=marks)],
        )


def _model(backend: str = "numpy", **kw):
    return SubstrateForwardModel(backend=backend, **kw)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_construction_default_dims(backend):
    m = _model(backend=backend)
    assert m.feature_dim == DEFAULT_FEATURE_DIM
    assert m.units == 32
    assert m.suspended is False
    assert m.device == "cpu"


def test_construction_custom_dims(backend):
    m = _model(backend=backend, feature_dim=4, units=16)
    assert m.feature_dim == 4
    assert m.units == 16


def test_construction_rejects_invalid(backend):
    with pytest.raises(ValueError):
        _model(backend=backend, feature_dim=0)
    with pytest.raises(ValueError):
        _model(backend=backend, units=0)
    with pytest.raises(ValueError):
        _model(backend=backend, lr=0.0)


def test_force_cuda_ignored_soma_forward_stays_on_cpu(backend, monkeypatch):
    """CPU-only by policy, mirroring Chronos's CfCNetwork pin."""
    monkeypatch.setenv("KAINE_FORCE_DEVICE", "cuda")
    m = _model(backend=backend, feature_dim=4, units=8)
    assert m.device == "cpu"


# ---------------------------------------------------------------------------
# Backend-specific reservoir checks
# ---------------------------------------------------------------------------

def test_is_ncps_cfc_backed(backend):
    """The torch backend must use a real ncps CfC; numpy uses the shared reservoir."""
    if backend == "torch":
        pytest.importorskip("ncps")
        from ncps.torch import CfC

        m = _model(backend="torch", feature_dim=4, units=8, seed=0)
        assert isinstance(m._cfc, CfC)
        # The reservoir is frozen — it never trains.
        assert all(not p.requires_grad for p in m._cfc.parameters())
        # Only the linear readout adapts online.
        assert all(p.requires_grad for p in m._readout.parameters())
    else:
        m = _model(backend="numpy", feature_dim=4, units=8, seed=0)
        assert m.backend == "numpy"
        assert hasattr(m, "_reservoir")


# ---------------------------------------------------------------------------
# predict()
# ---------------------------------------------------------------------------

def test_predict_returns_correct_shape(backend):
    m = _model(backend=backend, feature_dim=4, units=8, seed=42)
    out = m.predict([0.1, 0.2, 0.3, 0.4])
    assert len(out) == 4
    assert all(math.isfinite(v) for v in out)


def test_predict_does_not_mutate_recurrent_state(backend):
    """predict() is a side-effect-free peek; step() advances state."""
    m = _model(backend=backend, feature_dim=4, units=8, seed=42)
    m.predict([0.1, 0.2, 0.3, 0.4])
    assert m._hx is None
    m.predict([0.9, 0.9, 0.9, 0.9])
    assert m._hx is None


def test_predict_rejects_wrong_dim(backend):
    m = _model(backend=backend, feature_dim=4, units=8)
    with pytest.raises(ValueError):
        m.predict([0.1, 0.2])


# ---------------------------------------------------------------------------
# step() — first tick returns 0.0
# ---------------------------------------------------------------------------

def test_first_step_returns_zero_error(backend):
    m = _model(backend=backend, feature_dim=4, units=8, seed=42)
    err = m.step([0.1, 0.2, 0.3, 0.4])
    assert err == 0.0


def test_second_step_returns_finite_error(backend):
    m = _model(backend=backend, feature_dim=4, units=8, seed=42)
    m.step([0.1, 0.2, 0.3, 0.4])
    err = m.step([0.2, 0.3, 0.4, 0.5])
    assert math.isfinite(err)
    assert err >= 0.0


def test_step_advances_recurrent_state(backend):
    """Unlike predict(), step() commits the CfC hidden state forward."""
    m = _model(backend=backend, feature_dim=4, units=8, seed=0)
    assert m._hx is None
    m.step([0.1, 0.2, 0.3, 0.4])
    assert m._hx is not None


# ---------------------------------------------------------------------------
# Online adaptation reduces error on a stationary signal
# ---------------------------------------------------------------------------

def test_online_adaptation_reduces_error_on_stationary_signal(backend):
    """After many ticks on a fixed vector, prediction error should shrink."""
    m = _model(backend=backend, feature_dim=4, units=8, seed=0)
    feature = [0.5, 0.3, 0.2, 0.1]
    errors = []
    for _ in range(60):
        err = m.step(feature)
        errors.append(err)
    early = errors[5:15]
    late = errors[45:60]
    if early and late:
        assert sum(late) / len(late) < sum(early) / len(early), (
            f"expected late mean {sum(late)/len(late):.4f} < "
            f"early mean {sum(early)/len(early):.4f}"
        )


def test_adaptation_changes_readout_weights(backend):
    """step() must actually move the readout's weights over time."""
    m = _model(backend=backend, feature_dim=4, units=8, seed=0)
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

def test_nonfinite_loss_skips_update(backend):
    """When we inject a non-finite feature, the model must not crash."""
    m = _model(backend=backend, feature_dim=4, units=8, seed=0)
    m.step([0.1, 0.2, 0.3, 0.4])
    before = m.state_dict()
    err = m.step([float("inf"), float("nan"), 0.0, 0.0])
    assert err == 0.0
    after = m.state_dict()
    assert before["weight"] == after["weight"]
    assert before["bias"] == after["bias"]


def test_nonfinite_input_does_not_corrupt_recurrent_state(backend):
    """A non-finite feature must not be committed into the CfC hidden state."""
    m = _model(backend=backend, feature_dim=4, units=8, seed=0)
    m.step([0.1, 0.2, 0.3, 0.4])
    hx_before = m._hx
    m.step([float("inf"), float("nan"), 0.0, 0.0])
    assert m._hx is hx_before
    err = m.step([0.2, 0.2, 0.2, 0.2])
    assert math.isfinite(err)


# ---------------------------------------------------------------------------
# suspended flag freezes weights
# ---------------------------------------------------------------------------

def test_suspended_flag_freezes_weights(backend):
    m = _model(backend=backend, feature_dim=4, units=8, seed=1)
    feature = [0.5, 0.4, 0.3, 0.2]
    m.step(feature)
    before = m.state_dict()
    m.suspended = True
    for _ in range(20):
        m.step(feature)
    after = m.state_dict()
    assert before["weight"] == after["weight"]
    assert before["bias"] == after["bias"]


def test_suspended_flag_still_advances_recurrent_state(backend):
    """Suspending freezes the readout's weights, not the CfC's recurrent tick."""
    m = _model(backend=backend, feature_dim=4, units=8, seed=1)
    feature = [0.5, 0.4, 0.3, 0.2]
    m.step(feature)
    m.suspended = True
    hx_before = m._hx
    m.step(feature)
    assert m._hx is not hx_before


# ---------------------------------------------------------------------------
# Serialisation roundtrip (now preserves the reservoir seed)
# ---------------------------------------------------------------------------

def test_state_dict_roundtrip(backend):
    """A revived model with the same seed and loaded readout reproduces predictions."""
    m = _model(backend=backend, feature_dim=4, units=8, seed=42)
    for _ in range(5):
        m.step([0.1, 0.2, 0.3, 0.4])
    sd = m.state_dict()
    seed = m.reservoir_seed
    m.reset()
    pred1 = m.predict([0.5, 0.5, 0.5, 0.5])

    m2 = _model(backend=backend, feature_dim=4, units=8, seed=seed)
    m2.load_state_dict(sd)
    pred2 = m2.predict([0.5, 0.5, 0.5, 0.5])
    for a, b in zip(pred1, pred2):
        assert abs(a - b) < 1e-5


def test_state_dict_contains_no_raw_buffers(backend):
    """state_dict must contain only weight+bias, never raw feature/hidden data."""
    m = _model(backend=backend, feature_dim=4, units=8)
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

def test_salience_baseline_on_zero_error(backend):
    m = _model(backend=backend, feature_dim=4, units=8)
    s = m.prediction_error_to_salience(0.0, 0.1, 0.7)
    assert abs(s - 0.1) < 1e-6


def test_salience_in_range(backend):
    m = _model(backend=backend, feature_dim=4, units=8)
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
    vec = metrics_to_feature_vector(
        {"gpu_0_temp_c": 90.0},
        feature_dim=3,
    )
    assert len(vec) == 3
