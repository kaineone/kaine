# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
from collections import deque

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.positive_control import (
    POSITIVE_CONTROL_SOURCE,
    RESULT_EVENT_TYPE,
    ComponentSource,
    PositiveControl,
    PositiveControlSettings,
    publish_result,
)
from kaine.modules.topos.forward import LatentForwardModel

try:
    import torch
except Exception:  # pragma: no cover
    torch = None


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def test_settings_defaults():
    assert PositiveControlSettings.from_config(None) == PositiveControlSettings()
    assert PositiveControlSettings.from_config({}) == PositiveControlSettings()


def test_settings_unknown_key():
    with pytest.raises(ValueError, match="unknown keys in \\[positive_control\\]"):
        PositiveControlSettings.from_config({"enabled": True, "extra_key": 1})


def test_settings_enabled_requires_snr():
    with pytest.raises(ValueError, match="snr must be set"):
        PositiveControlSettings.from_config({"enabled": True})


def test_settings_min_effect_validation():
    with pytest.raises(ValueError, match="min_effect"):
        PositiveControlSettings.from_config({"min_effect": True})
    with pytest.raises(ValueError, match="min_effect"):
        PositiveControlSettings.from_config({"min_effect": -0.1})
    with pytest.raises(ValueError, match="min_effect"):
        PositiveControlSettings.from_config({"min_effect": 0.0})


def test_settings_min_reports_validation():
    with pytest.raises(ValueError, match="min_reports"):
        PositiveControlSettings.from_config({"min_reports": 0})
    with pytest.raises(ValueError, match="min_reports"):
        PositiveControlSettings.from_config({"min_reports": -1})
    with pytest.raises(ValueError, match="min_reports"):
        PositiveControlSettings.from_config({"min_reports": 2.5})
    with pytest.raises(ValueError, match="min_reports"):
        PositiveControlSettings.from_config({"min_reports": True})


def test_settings_snr_validation():
    with pytest.raises(ValueError, match="snr"):
        PositiveControlSettings.from_config({"snr": 0.0})
    with pytest.raises(ValueError, match="snr"):
        PositiveControlSettings.from_config({"snr": "ten"})


def test_settings_valid_section():
    section = {
        "enabled": True,
        "min_effect": 0.02,
        "min_reports": 10,
        "snr": 100.0,
        "seed": 5,
    }
    settings = PositiveControlSettings.from_config(section)
    assert settings == PositiveControlSettings(
        enabled=True, min_effect=0.02, min_reports=10, snr=100.0, seed=5
    )


def test_component_source():
    rng = np.random.default_rng(3)
    inputs = rng.standard_normal((2000, 4))

    src_a = ComponentSource(informative=True, snr=100.0, seed=0, processor="topos")
    src_b = ComponentSource(informative=True, snr=100.0, seed=0, processor="topos")
    out_a = np.array([src_a.next(v) for v in inputs])
    out_b = np.array([src_b.next(v) for v in inputs])
    assert np.allclose(out_a, out_b)

    src_n1 = ComponentSource(informative=False, snr=100.0, seed=0, processor="topos")
    src_n2 = ComponentSource(informative=False, snr=100.0, seed=0, processor="topos")
    out_n1 = np.array([src_n1.next(v) for v in inputs])
    out_n2 = np.array([src_n2.next(v) for v in inputs])
    assert np.allclose(out_n1, out_n2)

    projection = inputs @ src_a._u
    assert np.corrcoef(out_a, projection)[0, 1] > 0.9
    assert abs(np.corrcoef(out_n1, projection)[0, 1]) < 0.1
    assert abs(out_a.mean() - out_n1.mean()) < 0.1
    assert abs(out_a.std() - out_n1.std()) / out_a.std() < 0.15


def _run_topos_detection(min_effect, min_reports=500):
    settings = PositiveControlSettings(
        enabled=True, snr=100.0, min_effect=min_effect, min_reports=min_reports, seed=0
    )
    control = PositiveControl("topos", settings)
    live = LatentForwardModel(
        latent_dim=4, units=16, context_dim=24, seed=1, lr=0.05
    )

    rng = np.random.default_rng(7)
    ctx = [0.5] * 24
    null = [0.5] * 24
    live_errors = deque(maxlen=32)

    for _ in range(1000):
        x = rng.standard_normal(4).tolist()
        err = live.step(x, ctx, null)
        live_errors.append(err)

        if live.last_scored_had_context and live.last_null_error is not None:
            mean_err = sum(live_errors) / len(live_errors)
            live_gain = (
                (live.last_null_error - err) / mean_err if mean_err > 0 else None
            )
        else:
            mean_err = None
            live_gain = None

        control.after_report(live, x, ctx, null, live_gain, mean_err, awake=True)

    return control.result()


def test_detection_end_to_end():
    result = _run_topos_detection(min_effect=0.02)
    assert result["processor"] == "topos"
    assert result["n_reports"] > 900
    assert result["detected"] is True
    assert result["noise_detected"] is False
    assert result["passed"] is True
    assert result["effect"] > 0.02
    assert result["ig_without"] == pytest.approx(0.0, abs=1e-9)


def test_detection_without_min_effect():
    result = _run_topos_detection(min_effect=None)
    assert result["n_reports"] > 900
    assert isinstance(result["ig_with"], float)
    assert isinstance(result["ig_without"], float)
    assert isinstance(result["ig_noise"], float)
    assert result["detected"] is None
    assert result["noise_detected"] is None
    assert result["passed"] is None


def test_no_verdict_without_min_reports():
    result = _run_topos_detection(min_effect=0.02, min_reports=None)
    assert result["n_reports"] > 900
    assert result["detected"] is None
    assert result["noise_detected"] is None
    assert result["passed"] is None


def test_small_sample_does_not_pass():
    result = _run_topos_detection(min_effect=0.02, min_reports=5000)
    assert result["n_reports"] > 0
    assert result["detected"] is True
    assert result["passed"] is False


def _assert_state_equal(a, b):
    if isinstance(a, dict):
        assert isinstance(b, dict)
        assert set(a) == set(b)
        for key in a:
            _assert_state_equal(a[key], b[key])
    elif isinstance(a, np.ndarray):
        assert np.array_equal(a, b)
    elif torch is not None and isinstance(a, torch.Tensor):
        assert torch.equal(a, b)
    else:
        assert a == b


def test_live_model_untouched():
    settings = PositiveControlSettings(
        enabled=True, snr=100.0, min_effect=0.02, min_reports=1, seed=0
    )
    control = PositiveControl("topos", settings)

    live_with = LatentForwardModel(
        latent_dim=4, units=16, context_dim=24, seed=2, lr=0.05
    )
    live_without = LatentForwardModel(
        latent_dim=4, units=16, context_dim=24, seed=2, lr=0.05
    )

    rng = np.random.default_rng(11)
    ctx = [0.3] * 24
    null = [0.3] * 24
    errors_with = []
    errors_without = []
    nulls_with = []
    nulls_without = []

    for _ in range(200):
        x = rng.standard_normal(4).tolist()
        err_with = live_with.step(x, ctx, null)
        control.after_report(live_with, x, ctx, null, None, None, awake=True)
        err_without = live_without.step(x, ctx, null)

        errors_with.append(err_with)
        errors_without.append(err_without)
        nulls_with.append(live_with.last_null_error)
        nulls_without.append(live_without.last_null_error)

    assert errors_with == errors_without
    assert nulls_with == nulls_without
    _assert_state_equal(live_with.state_dict(), live_without.state_dict())


def test_asleep_reports_do_not_count():
    settings = PositiveControlSettings(enabled=True, snr=100.0, seed=0)
    control = PositiveControl("topos", settings)
    live = LatentForwardModel(
        latent_dim=4, units=16, context_dim=24, seed=3, lr=0.05
    )

    rng = np.random.default_rng(13)
    ctx = [0.0] * 24
    null = [0.0] * 24

    for _ in range(50):
        x = rng.standard_normal(4).tolist()
        live.step(x, ctx, null)
        ret = control.after_report(live, x, ctx, null, 0.0, 1.0, awake=False)
        assert ret is None

    result = control.result()
    assert result["n_reports"] == 0
    assert result["ig_with"] is None
    assert result["detected"] is None


@pytest.mark.asyncio
async def test_publish_result(bus):
    result = {
        "processor": "topos",
        "n_reports": 10,
        "ig_with": 0.1,
        "ig_without": 0.0,
        "ig_noise": 0.0,
        "effect": 0.1,
        "noise_effect": 0.0,
        "min_effect": 0.02,
        "min_reports": 1,
        "snr": 100.0,
        "detected": True,
        "noise_detected": False,
        "passed": True,
        "failed": False,
        "final": False,
    }
    await publish_result(bus, result)

    entries = await bus.read("positive_control.out", last_id="0")
    assert len(entries) == 1
    entry_id, event = entries[0]
    assert isinstance(event, Event)
    assert event.source == POSITIVE_CONTROL_SOURCE
    assert event.type == RESULT_EVENT_TYPE
    assert event.payload == result


def test_constructor_rejects_unknown_processor():
    settings = PositiveControlSettings(enabled=True, snr=10.0, seed=0)
    with pytest.raises(ValueError, match="processor"):
        PositiveControl("vision", settings)


def test_constructor_rejects_disabled():
    settings = PositiveControlSettings(enabled=False)
    with pytest.raises(ValueError, match="disabled"):
        PositiveControl("topos", settings)


def test_after_report_requires_model_methods():
    settings = PositiveControlSettings(enabled=True, snr=10.0, seed=0)
    control = PositiveControl("topos", settings)

    class NoMethods:
        pass

    with pytest.raises(TypeError, match="topos"):
        control.after_report(NoMethods(), [0.0], None, None, None, None, awake=True)


def test_non_informative_value_ignores_the_current_input():
    shared = [1.0, 2.0, 3.0, 4.0]
    source_a = ComponentSource(informative=False, snr=10.0, seed=7, processor="topos")
    source_b = ComponentSource(informative=False, snr=10.0, seed=7, processor="topos")
    for _ in range(20):
        source_a.next(shared)
        source_b.next(shared)
    assert source_a.next([1.0, 2.0, 3.0, 4.0]) == source_b.next([-50.0, 9.0, 0.0, 7.0])

    fresh = ComponentSource(informative=False, snr=10.0, seed=9, processor="audition")
    assert fresh.next([1.0, 2.0, 3.0]) == 0.0


def test_gains_share_the_live_denominator():
    settings = PositiveControlSettings(
        enabled=True, snr=10.0, min_effect=0.01, min_reports=1, seed=0
    )
    control = PositiveControl("topos", settings)
    control._probe_info.step = lambda *args, **kwargs: 0.2
    control._probe_noise.step = lambda *args, **kwargs: 0.0

    class Model:
        def widened_copy(self, n):
            return self

        def hindsight_step(self, *args, **kwargs):
            return (0.0, 0.0)

    result = control.after_report(Model(), [0.0], None, None, 0.1, 2.0, awake=True)
    assert result is not None
    assert result["ig_with"] == pytest.approx(0.1)
    assert result["ig_without"] == pytest.approx(0.1)
    assert result["ig_noise"] == pytest.approx(0.0)


def test_non_finite_gains_are_not_counted():
    settings = PositiveControlSettings(
        enabled=True, snr=10.0, min_effect=0.01, min_reports=1, seed=0
    )
    control = PositiveControl("topos", settings)
    control._probe_info.step = lambda *args, **kwargs: 0.2
    control._probe_noise.step = lambda *args, **kwargs: 0.0

    class Model:
        def widened_copy(self, n):
            return self

        def hindsight_step(self, *args, **kwargs):
            return (0.0, 0.0)

    model = Model()
    assert control.after_report(
        model, [0.0], None, None, float("nan"), 2.0, awake=True
    ) is None
    assert control.result()["n_reports"] == 0
    assert control.after_report(
        model, [0.0], None, None, 0.1, 0.0, awake=True
    ) is None
    assert control.result()["n_reports"] == 0


def test_final_and_failure_results():
    settings = PositiveControlSettings(
        enabled=True, snr=10.0, min_effect=0.01, min_reports=1, seed=0
    )
    control = PositiveControl("topos", settings)
    final = control.final_result()
    assert final["final"] is True
    assert final["failed"] is False
    failure = control.failure_result()
    assert failure["final"] is True
    assert failure["failed"] is True
    assert failure["passed"] is False


def test_non_finite_input_does_not_poison_the_control():
    settings = PositiveControlSettings(
        enabled=True, snr=100.0, min_effect=0.02, min_reports=100, seed=0
    )
    control = PositiveControl("topos", settings)
    live = LatentForwardModel(
        latent_dim=4, units=16, context_dim=24, seed=1, lr=0.05
    )

    rng = np.random.default_rng(7)
    ctx = [0.5] * 24
    null = [0.5] * 24
    live_errors = deque(maxlen=32)

    for i in range(300):
        if i == 150:
            x = [float("nan")] * 4
        else:
            x = rng.standard_normal(4).tolist()

        err = live.step(x, ctx, null)
        live_errors.append(err)

        if i == 150:
            control.after_report(live, x, ctx, null, None, None, awake=True)
        else:
            if live.last_scored_had_context and live.last_null_error is not None:
                mean_err = sum(live_errors) / len(live_errors)
                live_gain = (
                    (live.last_null_error - err) / mean_err
                    if mean_err > 0
                    else None
                )
            else:
                mean_err = None
                live_gain = None
            control.after_report(
                live, x, ctx, null, live_gain, mean_err, awake=True
            )

    result = control.result()
    assert result["n_reports"] > 0
    assert math.isfinite(result["ig_with"])
    assert math.isfinite(result["ig_without"])
    assert math.isfinite(result["ig_noise"])
    assert math.isfinite(result["effect"])


def test_failure_result_cannot_pass():
    settings = PositiveControlSettings(
        enabled=True, snr=10.0, min_effect=0.01, min_reports=1, seed=0
    )
    control = PositiveControl("topos", settings)
    assert control.result()["failed"] is False
    failed = control.failure_result()
    assert failed["failed"] is True
    assert failed["passed"] is False
    assert failed["final"] is True


def test_informative_noise_scale_ignores_the_current_input():
    snr = 10.0
    seed = 7
    processor = "topos"
    shared = [[float(i), float(i + 1), float(i + 2), float(i + 3)] for i in range(20)]
    a = [1.0, 2.0, 3.0, 4.0]
    b = [-5.0, 0.5, 2.0, 1.0]

    src_a = ComponentSource(informative=True, snr=snr, seed=seed, processor=processor)
    src_b = ComponentSource(informative=True, snr=snr, seed=seed, processor=processor)

    for x in shared:
        src_a.next(x)
        src_b.next(x)

    out_a = src_a.next(a)
    out_b = src_b.next(b)

    expected = float(np.dot(src_a._u, np.asarray(a))) - float(
        np.dot(src_a._u, np.asarray(b))
    )
    assert out_a - out_b == pytest.approx(expected, abs=1e-9)

    src = ComponentSource(informative=True, snr=snr, seed=seed + 1, processor=processor)
    x = [1.0, 2.0, 3.0, 4.0]
    out = src.next(x)
    assert out == pytest.approx(float(np.dot(src._u, np.asarray(x))), abs=1e-9)
