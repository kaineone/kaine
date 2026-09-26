# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import importlib.util

import pytest

from kaine.modules.chronos.network import CfCNetwork, ForwardPredictionHead

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


def _net(backend: str = "numpy", **kw):
    return CfCNetwork(backend=backend, **kw)


def _head(backend: str = "numpy", **kw):
    return ForwardPredictionHead(backend=backend, **kw)


def test_invalid_dimensions_rejected(backend):
    with pytest.raises(ValueError):
        _net(backend=backend, input_size=0, units=8)
    with pytest.raises(ValueError):
        _net(backend=backend, input_size=8, units=0)


def test_parameter_count_under_cap(backend):
    net = _net(backend=backend, input_size=24, units=32, seed=42)
    params = net.parameter_count()
    assert 0 < params < 100_000, f"got {params} params"


def test_hidden_state_shape(backend):
    net = _net(backend=backend, input_size=24, units=32, seed=0)
    out = net.tick([0.1] * 24)
    assert isinstance(out, list)
    assert len(out) == 32
    assert all(isinstance(v, float) for v in out)


def test_state_is_persistent_across_ticks(backend):
    net = _net(backend=backend, input_size=24, units=32, seed=0)
    h1 = net.tick([0.5] * 24)
    h2 = net.tick([0.5] * 24)
    # Identical inputs produce different outputs because the network is
    # stateful — hidden state carries forward.
    assert h1 != h2


def test_reset_clears_hidden_state(backend):
    net = _net(backend=backend, input_size=24, units=32, seed=0)
    h1 = net.tick([0.5] * 24)
    net.tick([0.7] * 24)
    net.reset()
    h_after_reset = net.tick([0.5] * 24)
    # h_after_reset should equal h1 (first-step output) since both start
    # from no hidden state with same input.
    assert h_after_reset == h1


def test_input_size_mismatch_rejected(backend):
    net = _net(backend=backend, input_size=24, units=32, seed=0)
    with pytest.raises(ValueError):
        net.tick([0.1] * 16)


def test_force_cuda_ignored_chronos_stays_on_cpu(backend, monkeypatch):
    monkeypatch.setenv("KAINE_FORCE_DEVICE", "cuda")
    net = _net(backend=backend, input_size=24, units=32, seed=0)
    # Chronos pins to cpu regardless of the env override
    assert net.device == "cpu"


# ---------------------------------------------------------------------------
# ForwardPredictionHead tests
# ---------------------------------------------------------------------------

def test_forward_prediction_head_output_shape(backend):
    """predict() returns a list of length input_size."""
    head = _head(backend=backend, input_size=24, units=32, seed=0)
    hidden = [0.1] * 32
    pred = head.predict(hidden)
    assert isinstance(pred, list)
    assert len(pred) == 24
    assert all(isinstance(v, float) for v in pred)


def test_forward_prediction_head_invalid_dims(backend):
    with pytest.raises(ValueError):
        _head(backend=backend, input_size=0, units=32)
    with pytest.raises(ValueError):
        _head(backend=backend, input_size=24, units=0)
    with pytest.raises(ValueError):
        _head(backend=backend, input_size=24, units=32, lr=0.0)


def test_forward_prediction_head_prediction_error_metric(backend):
    head = _head(backend=backend, input_size=4, units=8, seed=0)
    predicted = [1.0, 2.0, 3.0, 4.0]
    actual = [1.0, 2.0, 3.0, 4.0]
    assert head.prediction_error(predicted, actual) == pytest.approx(0.0)
    actual2 = [2.0, 3.0, 4.0, 5.0]
    assert head.prediction_error(predicted, actual2) == pytest.approx(1.0)


def test_forward_prediction_error_length_mismatch(backend):
    head = _head(backend=backend, input_size=4, units=8, seed=0)
    with pytest.raises(ValueError):
        head.prediction_error([1.0, 2.0], [1.0])


def test_forward_prediction_head_error_drops_on_regular_cadence(backend):
    """After adapting on a repeated constant input, prediction error decreases."""
    input_size = 8
    units = 16
    head = _head(
        backend=backend, input_size=input_size, units=units, seed=42, lr=0.05
    )
    fixed_hidden = [0.3] * units
    fixed_target = [0.5] * input_size

    errors = []
    for _ in range(200):
        pred = head.predict(fixed_hidden)
        err = head.prediction_error(pred, fixed_target)
        errors.append(err)
        head.adapt(fixed_hidden, fixed_target)

    early_mean = sum(errors[:20]) / 20
    late_mean = sum(errors[-20:]) / 20
    assert late_mean < early_mean, (
        f"Expected error to decrease with adaptation: "
        f"early={early_mean:.4f}, late={late_mean:.4f}"
    )


def test_forward_prediction_head_suspend_blocks_adaptation(backend):
    """With suspended=True, adapt() does not change weights."""
    head = _head(backend=backend, input_size=4, units=8, seed=0)
    head.suspended = True
    before = head.state_dict()
    hidden = [0.5] * 8
    target = [1.0] * 4
    for _ in range(10):
        head.adapt(hidden, target)
    after = head.state_dict()
    assert before["weight"] == after["weight"]
    assert before["bias"] == after["bias"]


def test_forward_prediction_head_state_dict_roundtrip(backend):
    """state_dict() / load_state_dict() reproduce weights exactly."""
    head = _head(backend=backend, input_size=4, units=8, seed=1, lr=0.1)
    hidden = [0.2] * 8
    target = [0.8] * 4
    for _ in range(5):
        head.adapt(hidden, target)

    snap = head.state_dict()
    pred_before = head.predict(hidden)

    fresh = _head(backend=backend, input_size=4, units=8, seed=99)
    fresh.load_state_dict(snap)
    pred_after = fresh.predict(hidden)
    assert pred_before == pytest.approx(pred_after, abs=1e-5)
