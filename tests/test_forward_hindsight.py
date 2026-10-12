# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
import random

import pytest

from kaine.modules.audition.forward import AuditoryForwardModel
from kaine.modules.interoception.forward import SubstrateForwardModel
from kaine.modules.vision.forward import LatentForwardModel

torch = pytest.importorskip("torch")


@pytest.mark.parametrize(
    "model_cls, dim, init_kw",
    [
        (LatentForwardModel, 4, {"latent_dim": 4, "units": 8, "context_dim": 24, "seed": 3}),
        (AuditoryForwardModel, 6, {"feature_dim": 6, "units": 8, "context_dim": 24, "seed": 3}),
    ],
)
def test_widened_copy_predicts_like_the_original(model_cls, dim, init_kw):
    live = model_cls(**init_kw)
    base_ctx = [0.2] * 24
    for i in range(3):
        live.step([0.1 * (i + 1)] * dim, base_ctx)
    twin = live.widened_copy(1)
    assert twin.context_dim == 25
    x = [0.5] * dim
    assert twin.predict(x, base_ctx + [7.0]) == pytest.approx(live.predict(x, base_ctx))


@pytest.mark.parametrize(
    "model_cls, init_kw",
    [
        (LatentForwardModel, {"latent_dim": 4, "units": 8, "context_dim": 24, "seed": 3}),
        (AuditoryForwardModel, {"feature_dim": 6, "units": 8, "context_dim": 24, "seed": 3}),
    ],
)
def test_widened_copy_leaves_the_global_rng(model_cls, init_kw):
    live = model_cls(**init_kw)
    state = torch.get_rng_state()
    live.widened_copy(1)
    assert torch.equal(torch.get_rng_state(), state)


@pytest.mark.parametrize(
    "model_cls, init_kw",
    [
        (
            LatentForwardModel,
            {"latent_dim": 4, "units": 8, "context_dim": 24, "seed": 3},
        ),
        (
            AuditoryForwardModel,
            {"feature_dim": 6, "units": 8, "context_dim": 24, "seed": 3},
        ),
        (
            SubstrateForwardModel,
            {
                "feature_dim": 4,
                "units": 8,
                "context_dim": 24,
                "seed": 3,
                "backend": "numpy",
            },
        ),
    ],
)
def test_widened_copy_draws_no_random_numbers(model_cls, init_kw, monkeypatch):
    def _raise(**kwargs):
        raise RuntimeError("fork_rng must not be called")

    monkeypatch.setattr(torch.random, "fork_rng", _raise)
    live = model_cls(**init_kw)
    state = torch.get_rng_state()
    twin = live.widened_copy(1)
    assert twin.context_dim == live.context_dim + 1
    assert torch.equal(torch.get_rng_state(), state)


def test_widened_copy_draws_no_random_numbers_interoception_torch(monkeypatch):
    pytest.importorskip("ncps")

    def _raise(**kwargs):
        raise RuntimeError("fork_rng must not be called")

    monkeypatch.setattr(torch.random, "fork_rng", _raise)
    live = SubstrateForwardModel(
        feature_dim=4,
        units=8,
        context_dim=24,
        seed=3,
        backend="torch",
    )
    state = torch.get_rng_state()
    twin = live.widened_copy(1)
    assert twin.context_dim == 25
    assert torch.equal(torch.get_rng_state(), state)


@pytest.mark.parametrize(
    "model_cls, dim, init_kw",
    [
        (LatentForwardModel, 4, {"latent_dim": 4, "units": 8, "context_dim": 24, "seed": 3}),
        (AuditoryForwardModel, 6, {"feature_dim": 6, "units": 8, "context_dim": 24, "seed": 3}),
    ],
)
def test_hindsight_matches_the_live_step(model_cls, dim, init_kw):
    live = model_cls(**init_kw)
    rng = random.Random(0)
    inputs = [[rng.random() for _ in range(dim)] for _ in range(12)]
    contexts = [[rng.random() for _ in range(24)] for _ in range(12)]
    null_ctx = [0.5] * 24
    live.step(inputs[0], contexts[0], contexts[0])
    twin = live.widened_copy(1)
    for t in range(1, 12):
        err = live.step(inputs[t], contexts[t], null_ctx)
        prev_ctx = contexts[t - 1] + [0.0]
        prev_null = (contexts[0] if t == 1 else null_ctx) + [0.0]
        h_err, h_null = twin.hindsight_step(inputs[t], prev_ctx, prev_null)
        assert h_err == pytest.approx(err, rel=1e-5, abs=1e-6)
        assert h_null == pytest.approx(live.last_null_error, rel=1e-5, abs=1e-6)


def test_interoception_hindsight_matches_the_live_step():
    live = SubstrateForwardModel(feature_dim=8, units=16, seed=5, context_dim=24)
    rng = random.Random(1)
    features = [[rng.random() for _ in range(8)] for _ in range(12)]
    contexts = [[rng.random() for _ in range(24)] for _ in range(12)]
    null_ctx = [0.5] * 24
    live.step(features[0], context=contexts[0], null_context=contexts[0], timespan=1.0)
    twin = live.widened_copy(1)
    for t in range(1, 12):
        err = live.step(
            features[t], context=contexts[t], null_context=null_ctx, timespan=1.0
        )
        prev_ctx = (contexts[0] if t == 1 else contexts[t - 1]) + [0.0]
        prev_null = (contexts[0] if t == 1 else null_ctx) + [0.0]
        h_err, h_null = twin.hindsight_step(
            features[t], prev_ctx, prev_null, timespan=1.0
        )
        assert h_err == pytest.approx(err, rel=1e-5, abs=1e-6)
        assert h_null == pytest.approx(live.last_null_error, rel=1e-5, abs=1e-6)


def test_interoception_widened_copy_predicts_like_the_original():
    live = SubstrateForwardModel(feature_dim=8, units=16, seed=5, context_dim=24)
    for i in range(3):
        live.step(
            [0.1 * (i + 1)] * 8,
            context=[0.2] * 24,
            null_context=[0.2] * 24,
            timespan=1.0,
        )
    twin = live.widened_copy(1)
    assert twin.context_dim == 25
    h = live._last_hidden
    ctx = [0.3] * 24
    assert twin._readout_predict(h, ctx + [9.0]) == pytest.approx(
        live._readout_predict(h, ctx)
    )


def test_interoception_hindsight_skips_a_non_finite_reading():
    live = SubstrateForwardModel(feature_dim=8, units=16, seed=5, context_dim=24)
    live.step([0.1] * 8, context=[0.0] * 24, null_context=[0.0] * 24, timespan=1.0)
    live.step([0.2] * 8, context=[0.0] * 24, null_context=[0.0] * 24, timespan=1.0)
    twin = live.widened_copy(1)
    assert twin.hindsight_step([float("nan")] * 8, [0.0] * 25, None) == (None, None)
    assert twin.hindsight_step([0.4] * 8, [0.0] * 25, None) == (None, None)
    h_err, _ = twin.hindsight_step([0.5] * 8, [0.0] * 25, None)
    assert isinstance(h_err, float)


@pytest.mark.parametrize(
    "model_cls, init_kw",
    [
        (LatentForwardModel, {"latent_dim": 4, "units": 8, "context_dim": 24, "seed": 3}),
        (AuditoryForwardModel, {"feature_dim": 6, "units": 8, "context_dim": 24, "seed": 3}),
        (SubstrateForwardModel, {"feature_dim": 8, "units": 16, "seed": 5, "context_dim": 24}),
    ],
)
def test_widened_copy_rejects_zero_extra(model_cls, init_kw):
    live = model_cls(**init_kw)
    with pytest.raises(ValueError):
        live.widened_copy(0)


@pytest.mark.parametrize(
    "model_cls, dim, init_kw",
    [
        (LatentForwardModel, 4, {"latent_dim": 4, "units": 8, "context_dim": 24, "seed": 3}),
        (AuditoryForwardModel, 6, {"feature_dim": 6, "units": 8, "context_dim": 24, "seed": 3}),
    ],
)
def test_hindsight_skips_a_non_finite_input(model_cls, dim, init_kw):
    live = model_cls(**init_kw)
    live.step([0.1] * dim, [0.2] * 24, [0.2] * 24)
    live.step([0.2] * dim, [0.2] * 24, [0.2] * 24)
    twin = live.widened_copy(1)
    buf_len = len(twin._buffer)
    result = twin.hindsight_step([float("nan")] * dim, [0.0] * 25, None)
    assert result == (None, None)
    assert len(twin._buffer) == buf_len
    # The first finite reading after a skip only re-seeds the pairing.
    error, null_error = twin.hindsight_step([0.3] * dim, [0.0] * 25, [0.0] * 25)
    assert error is None
    assert null_error is None
    assert len(twin._buffer) == buf_len + 1
    # The next reading is the first one scored from the re-seeded state.
    error, null_error = twin.hindsight_step([0.4] * dim, [0.0] * 25, [0.0] * 25)
    assert error is not None
    assert null_error is not None
    assert math.isfinite(error)
    assert math.isfinite(null_error)


@pytest.mark.parametrize(
    "model_cls, dim, init_kw",
    [
        (LatentForwardModel, 4, {"latent_dim": 4, "units": 8, "context_dim": 24, "seed": 3}),
        (AuditoryForwardModel, 6, {"feature_dim": 6, "units": 8, "context_dim": 24, "seed": 3}),
    ],
)
def test_step_skips_a_non_finite_input(model_cls, dim, init_kw):
    live = model_cls(**init_kw)
    ctx = [0.2] * 24
    live.step([0.1] * dim, ctx, ctx)
    assert live.last_error_defined is True  # first step error is 0 by definition
    live.step([0.2] * dim, ctx, ctx)
    assert live.last_null_error is not None
    buffer_before = [list(v) for v in live._buffer]
    weights_before = [p.detach().clone() for p in live._net.parameters()]
    assert live.step([float("nan")] * dim, ctx, ctx) == 0.0
    assert live.last_error_defined is False  # skipped input has no defined error
    assert live.last_reading_skipped is True
    assert live.last_null_error is None
    assert live.last_scored_had_context is False
    assert [list(v) for v in live._buffer] == buffer_before
    for saved, current in zip(weights_before, live._net.parameters()):
        assert torch.equal(saved, current)
    assert live.step([0.3] * dim, ctx, ctx) == 0.0
    assert live.last_error_defined is False  # first finite step after a skip has no prediction to score
    assert live.last_reading_skipped is False
    assert live.last_null_error is None
    assert len(live._buffer) == len(buffer_before) + 1
    for saved, current in zip(weights_before, live._net.parameters()):
        assert torch.equal(saved, current)
    error = live.step([0.4] * dim, ctx, ctx)
    assert live.last_error_defined is True  # second finite step after a skip is scored
    assert math.isfinite(error)
    assert error > 0
    assert live.last_null_error is not None
    assert live.last_scored_had_context is True


@pytest.mark.parametrize(
    "model_cls, dim, init_kw",
    [
        (LatentForwardModel, 4, {"latent_dim": 4, "units": 8, "context_dim": 24, "seed": 3}),
        (AuditoryForwardModel, 6, {"feature_dim": 6, "units": 8, "context_dim": 24, "seed": 3}),
    ],
)
def test_hindsight_matches_the_live_step_across_a_skip(model_cls, dim, init_kw):
    live = model_cls(**init_kw)
    rng = random.Random(2)
    inputs = [[rng.random() for _ in range(dim)] for _ in range(12)]
    contexts = [[rng.random() for _ in range(24)] for _ in range(12)]
    null_ctx = [0.5] * 24
    inputs[5] = [float("nan")] * dim
    live.step(inputs[0], contexts[0], contexts[0])
    twin = live.widened_copy(1)
    for t in range(1, 12):
        err = live.step(inputs[t], contexts[t], null_ctx)
        prev_ctx = contexts[t - 1] + [0.0]
        prev_null = (contexts[0] if t == 1 else null_ctx) + [0.0]
        h_err, h_null = twin.hindsight_step(inputs[t], prev_ctx, prev_null)
        if t in (5, 6):
            assert err == 0.0
            assert live.last_null_error is None
            assert (h_err, h_null) == (None, None)
        else:
            assert h_err == pytest.approx(err, rel=1e-5, abs=1e-6)
            assert h_null == pytest.approx(live.last_null_error, rel=1e-5, abs=1e-6)


@pytest.mark.parametrize(
    "model_cls, dim, init_kw",
    [
        (LatentForwardModel, 4, {"latent_dim": 4, "units": 8, "context_dim": 24, "seed": 3}),
        (AuditoryForwardModel, 6, {"feature_dim": 6, "units": 8, "context_dim": 24, "seed": 3}),
    ],
)
def test_widened_copy_after_a_skip_reseeds_with_the_live_model(model_cls, dim, init_kw):
    live = model_cls(**init_kw)
    rng = random.Random(3)
    inputs = [[rng.random() for _ in range(dim)] for _ in range(8)]
    contexts = [[rng.random() for _ in range(24)] for _ in range(8)]
    null_ctx = [0.5] * 24
    live.step(inputs[0], contexts[0], null_ctx)
    live.step(inputs[1], contexts[1], null_ctx)
    live.step([float("nan")] * dim, contexts[2], null_ctx)
    twin = live.widened_copy(1)
    for t in range(3, 8):
        err = live.step(inputs[t], contexts[t], null_ctx)
        h_err, h_null = twin.hindsight_step(
            inputs[t], contexts[t - 1] + [0.0], null_ctx + [0.0]
        )
        if t == 3:
            assert err == 0.0
            assert (h_err, h_null) == (None, None)
        else:
            assert h_err == pytest.approx(err, rel=1e-5, abs=1e-6)
            assert h_null == pytest.approx(live.last_null_error, rel=1e-5, abs=1e-6)
