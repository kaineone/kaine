# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.chronos.network import CfCNetwork, ForwardPredictionHead


def test_invalid_dimensions_rejected():
    with pytest.raises(ValueError):
        CfCNetwork(input_size=0, units=8)
    with pytest.raises(ValueError):
        CfCNetwork(input_size=8, units=0)


def test_parameter_count_under_cap():
    net = CfCNetwork(input_size=24, units=32, seed=42)
    params = net.parameter_count()
    assert 0 < params < 100_000, f"got {params} params"


def test_hidden_state_shape():
    net = CfCNetwork(input_size=24, units=32, seed=0)
    out = net.tick([0.1] * 24)
    assert isinstance(out, list)
    assert len(out) == 32
    assert all(isinstance(v, float) for v in out)


def test_state_is_persistent_across_ticks():
    net = CfCNetwork(input_size=24, units=32, seed=0)
    h1 = net.tick([0.5] * 24)
    h2 = net.tick([0.5] * 24)
    # Identical inputs produce different outputs because the network is
    # stateful — hidden state carries forward.
    assert h1 != h2


def test_reset_clears_hidden_state():
    net = CfCNetwork(input_size=24, units=32, seed=0)
    h1 = net.tick([0.5] * 24)
    net.tick([0.7] * 24)
    net.reset()
    h_after_reset = net.tick([0.5] * 24)
    # h_after_reset should equal h1 (first-step output) since both start
    # from no hidden state with same input.
    assert h_after_reset == h1


def test_input_size_mismatch_rejected():
    net = CfCNetwork(input_size=24, units=32, seed=0)
    with pytest.raises(ValueError):
        net.tick([0.1] * 16)


def test_force_cuda_ignored_chronos_stays_on_cpu(monkeypatch):
    monkeypatch.setenv("KAINE_FORCE_DEVICE", "cuda")
    net = CfCNetwork(input_size=24, units=32, seed=0)
    # Chronos pins to cpu regardless of the env override
    assert net.device == "cpu"


# ---------------------------------------------------------------------------
# ForwardPredictionHead tests
# ---------------------------------------------------------------------------

def test_forward_prediction_head_output_shape():
    """predict() returns a list of length input_size."""
    head = ForwardPredictionHead(input_size=24, units=32, seed=0)
    hidden = [0.1] * 32
    pred = head.predict(hidden)
    assert isinstance(pred, list)
    assert len(pred) == 24
    assert all(isinstance(v, float) for v in pred)


def test_forward_prediction_head_invalid_dims():
    with pytest.raises(ValueError):
        ForwardPredictionHead(input_size=0, units=32)
    with pytest.raises(ValueError):
        ForwardPredictionHead(input_size=24, units=0)
    with pytest.raises(ValueError):
        ForwardPredictionHead(input_size=24, units=32, lr=0.0)


def test_forward_prediction_head_prediction_error_metric():
    head = ForwardPredictionHead(input_size=4, units=8, seed=0)
    predicted = [1.0, 2.0, 3.0, 4.0]
    actual = [1.0, 2.0, 3.0, 4.0]
    assert head.prediction_error(predicted, actual) == pytest.approx(0.0)
    actual2 = [2.0, 3.0, 4.0, 5.0]
    assert head.prediction_error(predicted, actual2) == pytest.approx(1.0)


def test_forward_prediction_error_length_mismatch():
    head = ForwardPredictionHead(input_size=4, units=8, seed=0)
    with pytest.raises(ValueError):
        head.prediction_error([1.0, 2.0], [1.0])


def test_forward_prediction_head_error_drops_on_regular_cadence():
    """After adapting on a repeated constant input, prediction error decreases.

    This validates the spec scenario: events on a steady, predictable cadence
    yield low prediction error after adaptation.
    """
    input_size = 8
    units = 16
    head = ForwardPredictionHead(input_size=input_size, units=units, seed=42, lr=0.05)
    # Simulate a fixed hidden state (as if the CfC converged) and a fixed target
    fixed_hidden = [0.3] * units
    fixed_target = [0.5] * input_size

    # Collect errors over many adapt-then-measure cycles
    errors = []
    for _ in range(200):
        pred = head.predict(fixed_hidden)
        err = head.prediction_error(pred, fixed_target)
        errors.append(err)
        head.adapt(fixed_hidden, fixed_target)

    # Error in the last 20 ticks must be strictly lower than in the first 20
    early_mean = sum(errors[:20]) / 20
    late_mean = sum(errors[-20:]) / 20
    assert late_mean < early_mean, (
        f"Expected error to decrease with adaptation: "
        f"early={early_mean:.4f}, late={late_mean:.4f}"
    )


def test_forward_prediction_head_suspend_blocks_adaptation():
    """With suspended=True, adapt() does not change weights."""
    head = ForwardPredictionHead(input_size=4, units=8, seed=0)
    head.suspended = True
    before = head.state_dict()
    hidden = [0.5] * 8
    target = [1.0] * 4
    for _ in range(10):
        head.adapt(hidden, target)
    after = head.state_dict()
    assert before["weight"] == after["weight"]
    assert before["bias"] == after["bias"]


def test_forward_prediction_head_state_dict_roundtrip():
    """state_dict() / load_state_dict() reproduce weights exactly."""
    head = ForwardPredictionHead(input_size=4, units=8, seed=1, lr=0.1)
    hidden = [0.2] * 8
    target = [0.8] * 4
    # Adapt a few steps to move weights away from init
    for _ in range(5):
        head.adapt(hidden, target)

    snap = head.state_dict()
    pred_before = head.predict(hidden)

    # Load into a fresh head and confirm predictions match
    fresh = ForwardPredictionHead(input_size=4, units=8, seed=99)
    fresh.load_state_dict(snap)
    pred_after = fresh.predict(hidden)
    assert pred_before == pytest.approx(pred_after, abs=1e-5)
