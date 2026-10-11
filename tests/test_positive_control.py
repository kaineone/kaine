# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
from collections import deque

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.experiment.calibration_rules import SNR_LADDER
from kaine.experiment.planned_test_settings import (
    write_settings_record,
)
from kaine.experiment.principal_component import (
    PrincipalComponent,
    PrincipalComponentError,
    file_sha256,
    load_principal_component,
    principal_component_path,
    write_principal_component,
)
from kaine.modules.positive_control import (
    LADDER_EVENT_TYPE,
    POSITIVE_CONTROL_SOURCE,
    RESULT_EVENT_TYPE,
    ComponentSource,
    PositiveControl,
    PositiveControlSettings,
    ShadowProbe,
    publish_result,
)
from kaine.modules.topos.forward import LatentForwardModel

try:
    import torch
except Exception:  # pragma: no cover
    torch = None


def _pc(processor, dim, direction=None):
    if direction is None:
        direction = np.zeros(dim, dtype=float)
        direction[0] = 1.0
    else:
        direction = np.asarray(direction, dtype=float)
    norm = np.linalg.norm(direction)
    if norm == 0.0:
        raise ValueError("direction must not be zero")
    direction = tuple(direction / norm)
    mean = tuple(0.0 for _ in range(dim))
    return PrincipalComponent(
        processor=processor,
        run_id="test-run",
        n_inputs=100,
        dim=dim,
        mean=mean,
        direction=direction,
        variance=1.0,
        total_variance=float(dim),
    )


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def test_settings_defaults(tmp_path):
    assert PositiveControlSettings.from_config(None) == PositiveControlSettings()
    assert PositiveControlSettings.from_config({}) == PositiveControlSettings()
    disabled = PositiveControlSettings.from_config(
        {"enabled": False}, pc_root=tmp_path
    )
    assert disabled.enabled is False
    assert disabled.pc_root == str(tmp_path)


def test_settings_unknown_key():
    with pytest.raises(ValueError, match="unknown keys in \\[positive_control\\]"):
        PositiveControlSettings.from_config({"enabled": True, "extra_key": 1})


def test_settings_legacy_keys_rejected():
    for key in ("snr", "min_effect", "min_reports"):
        with pytest.raises(ValueError, match="settings record"):
            PositiveControlSettings.from_config({"enabled": False, key: 1})


def test_settings_enabled_without_mode():
    with pytest.raises(ValueError, match="mode must be one of"):
        PositiveControlSettings.from_config({"enabled": True})


def test_settings_unknown_mode():
    with pytest.raises(ValueError, match="mode must be one of"):
        PositiveControlSettings.from_config({"enabled": True, "mode": "debug"})


def test_settings_estimate_pc_rejects_run_or_record():
    with pytest.raises(ValueError, match="principal_components_run"):
        PositiveControlSettings.from_config(
            {"enabled": True, "mode": "estimate_pc", "principal_components_run": "x"}
        )
    with pytest.raises(ValueError, match="settings_record"):
        PositiveControlSettings.from_config(
            {"enabled": True, "mode": "estimate_pc", "settings_record": "x"}
        )


def test_settings_ladder_needs_preliminary_run(tmp_path):
    with pytest.raises(ValueError, match="principal_components_run"):
        PositiveControlSettings.from_config(
            {"enabled": True, "mode": "ladder"}, pc_root=tmp_path
        )


def test_settings_ladder_loads_principal_components(tmp_path):
    run_id = "prelim"
    shas = {}
    for processor in ("topos", "audition", "soma"):
        pc = _pc(processor, 4)
        path = principal_component_path(tmp_path, run_id, processor)
        write_principal_component(pc, path)
        shas[processor] = file_sha256(path)

    settings = PositiveControlSettings.from_config(
        {"enabled": True, "mode": "ladder", "principal_components_run": run_id},
        pc_root=tmp_path,
    )
    assert settings.mode == "ladder"
    for processor in ("topos", "audition", "soma"):
        assert settings.principal_components[processor].processor == processor
        assert settings.pc_sha256[processor] == shas[processor]


def test_settings_ladder_missing_file(tmp_path):
    run_id = "prelim"
    for processor in ("topos", "audition"):
        write_principal_component(
            _pc(processor, 4), principal_component_path(tmp_path, run_id, processor)
        )

    with pytest.raises(ValueError, match=str(principal_component_path(tmp_path, run_id, "soma"))):
        PositiveControlSettings.from_config(
            {"enabled": True, "mode": "ladder", "principal_components_run": run_id},
            pc_root=tmp_path,
        )


def test_settings_control_needs_record(tmp_path):
    with pytest.raises(ValueError, match="settings_record"):
        PositiveControlSettings.from_config(
            {"enabled": True, "mode": "control"}, pc_root=tmp_path
        )


def _write_settings_record(tmp_path, complete=True):
    from kaine.experiment import calibration_rules as rules
    run_id = "prelim"
    pc_refs = {}
    for processor in ("topos", "audition", "soma"):
        pc = _pc(processor, 4)
        path = principal_component_path(tmp_path, run_id, processor)
        write_principal_component(pc, path)
        pc_refs[processor] = {
            "path": str(path.resolve()),
            "sha256": file_sha256(path),
        }

    theta_eff = {"matched": 0.02, "pooled": 0.03}

    preliminary = {
        "run_id": "prelim",
        "seed": 1,
        "manifest_sha256": "a" * 64,
        "records_sha256": "b" * 64,
    }

    pilots = []
    for seed in range(2, 2 + rules.N_CAL):
        runs = {}
        for arm in ("competitive", "matched", "pooled"):
            runs[arm] = {
                "run_id": f"pilot{seed}_{arm}",
                "manifest_sha256": "c" * 64,
                "records_sha256": "d" * 64,
            }
        pilots.append({"seed": seed, "counted": True, "runs": runs})

    record = {
        "schema": "kaine.planned_test_settings",
        "schema_version": 1,
        "complete": complete,
        "blocked": {},
        "inputs": {"preliminary": preliminary, "pilots": pilots},
        "constants": {
            "n_cal": rules.N_CAL,
            "c_eff": rules.C_EFF,
            "q_pow": float(rules.Q_POW),
            "target_power": float(rules.TARGET_POWER),
            "alpha_test": float(rules.ALPHA_TEST),
            "mser_batch": rules.MSER_BATCH,
            "mser_ignore_end": rules.MSER_IGNORE_END,
            "mser_min_batches": rules.MSER_MIN_BATCHES,
            "n_bins": rules.N_BINS,
            "snr_ladder": list(rules.SNR_LADDER),
        },
        "values": {
            "t_learn_s": 120.0,
            "theta_eff": theta_eff,
            "min_effect": min(theta_eff.values()) / 2.0,
            "min_reports": 500,
            "n_attempted": rules.N_CAL,
            "n_not_exercised": 0,
            "n_counted": rules.N_CAL,
            "n_exact": rules.N_EXACT,
            "snr": {"topos": 4.0, "audition": 4.0, "soma": 4.0},
            "principal_components": pc_refs,
        },
    }
    settings_path = tmp_path / "settings.json"
    write_settings_record(record, settings_path)
    return settings_path


def test_settings_control_loads_record(tmp_path):
    settings_path = _write_settings_record(tmp_path)
    settings = PositiveControlSettings.from_config(
        {"enabled": True, "mode": "control", "settings_record": str(settings_path)},
        pc_root=tmp_path,
    )
    assert settings.mode == "control"
    assert settings.t_learn_s == 120.0
    assert settings.min_effect == 0.01
    assert settings.min_reports == 500
    assert settings.snr == {"topos": 4.0, "audition": 4.0, "soma": 4.0}
    assert settings.settings_sha256 is not None
    for processor in ("topos", "audition", "soma"):
        assert processor in settings.principal_components
        assert settings.pc_sha256[processor] == file_sha256(
            principal_component_path(tmp_path, "prelim", processor)
        )


def test_settings_control_rejects_incomplete_record(tmp_path):
    settings_path = _write_settings_record(tmp_path, complete=False)
    with pytest.raises(ValueError, match="planned-test settings record"):
        PositiveControlSettings.from_config(
            {"enabled": True, "mode": "control", "settings_record": str(settings_path)},
            pc_root=tmp_path,
        )


def test_informative_component_follows_principal_direction():
    rng = np.random.default_rng(5)
    dim = 8
    v = rng.standard_normal(dim)
    v /= np.linalg.norm(v)
    pc = _pc("topos", dim, direction=v)

    src = ComponentSource(
        informative=True, snr=1e6, seed=1, processor="topos", slot=0, pc=pc
    )
    inputs = rng.standard_normal((200, dim))
    projections = np.array([pc.project(x) for x in inputs])
    outputs = np.array([src.next(x) for x in inputs])
    assert np.corrcoef(outputs[2:], projections[2:])[0, 1] > 0.999

    src_noise = ComponentSource(
        informative=False, snr=1e6, seed=1, processor="topos", slot=0, pc=pc
    )
    noise_outputs = np.array([src_noise.next(x) for x in inputs])
    assert abs(np.corrcoef(noise_outputs[2:], projections[2:])[0, 1]) < 0.2


def test_component_source_rejects_wrong_input_length():
    pc = _pc("topos", 3)
    src = ComponentSource(
        informative=True, snr=1.0, seed=0, processor="topos", slot=0, pc=pc
    )
    with pytest.raises(PrincipalComponentError):
        src.next([1.0, 2.0])


def test_null_uses_the_component_mean_before_this_step():
    calls = []

    class StubShadow:
        context_dim = 25

        def hindsight_step(self, x, ctx, null_ctx, **kwargs):
            calls.append((list(ctx), list(null_ctx)))
            return (1.0, 1.0)

    class StubLive:
        def widened_copy(self, extra):
            return StubShadow()

        def hindsight_step(self, *args, **kwargs):
            raise AssertionError("the live model is never stepped in hindsight")

    class StubSource:
        def __init__(self):
            self._values = iter([1.0, 3.0, 5.0])

        def next(self, x):
            return next(self._values)

    probe = ShadowProbe(
        ComponentSource(
            informative=True,
            snr=1.0,
            seed=0,
            processor="topos",
            slot=1,
            pc=_pc("topos", 4),
        )
    )
    probe._source = StubSource()

    for _ in range(4):
        probe.step(StubLive(), [0.0], [0.0] * 24, [0.0] * 24)

    assert len(calls) == 3
    assert calls[0][0][-1] == 1.0
    assert calls[0][1][-1] == 0.0
    assert calls[1][0][-1] == 3.0
    assert calls[1][1][-1] == pytest.approx(1.0)
    assert calls[2][0][-1] == 5.0
    assert calls[2][1][-1] == pytest.approx(2.0)


def test_prepare_builds_the_shadows():
    pc = _pc("topos", 2)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 1.0},
        min_effect=0.1,
        min_reports=1,
        t_learn_s=0.0,
    )
    live = LatentForwardModel(2, 4, context_dim=8, seed=0)
    control = PositiveControl("topos", settings)
    control.prepare(live)
    assert control._probes[0]._shadow is not None
    assert control._probes[1]._shadow is not None
    result = control.after_report(
        live,
        [0.0] * 2,
        [0.0] * 8,
        [0.0] * 8,
        0.5,
        1.0,
        awake=True,
        entity_time_s=0.0,
    )
    assert result is None
    assert control.result()["n_reports"] == 0


def test_component_source():
    pc = _pc("topos", 4, direction=np.array([1.0, 0.0, 0.0, 0.0]))
    rng = np.random.default_rng(3)
    inputs = rng.standard_normal((2000, 4))

    src_a = ComponentSource(
        informative=True, snr=100.0, seed=0, processor="topos", slot=0, pc=pc
    )
    src_b = ComponentSource(
        informative=True, snr=100.0, seed=0, processor="topos", slot=0, pc=pc
    )
    out_a = np.array([src_a.next(v) for v in inputs])
    out_b = np.array([src_b.next(v) for v in inputs])
    assert np.allclose(out_a, out_b)

    src_n1 = ComponentSource(
        informative=False, snr=100.0, seed=0, processor="topos", slot=0, pc=pc
    )
    src_n2 = ComponentSource(
        informative=False, snr=100.0, seed=0, processor="topos", slot=0, pc=pc
    )
    out_n1 = np.array([src_n1.next(v) for v in inputs])
    out_n2 = np.array([src_n2.next(v) for v in inputs])
    assert np.allclose(out_n1, out_n2)

    projection = np.array([pc.project(v) for v in inputs])
    assert np.corrcoef(out_a, projection)[0, 1] > 0.9
    assert abs(np.corrcoef(out_n1, projection)[0, 1]) < 0.1
    assert abs(out_a.mean() - out_n1.mean()) < 0.1
    assert abs(out_a.std() - out_n1.std()) / out_a.std() < 0.15


def _run_topos_detection(min_effect, min_reports=500):
    pc = _pc("topos", 4, direction=np.array([1.0, 0.0, 0.0, 0.0]))
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 100.0},
        min_effect=min_effect,
        min_reports=min_reports,
        t_learn_s=0.0,
    )
    control = PositiveControl("topos", settings)
    live = LatentForwardModel(
        latent_dim=4, units=16, context_dim=24, seed=1, lr=0.05
    )

    rng = np.random.default_rng(7)
    ctx = [0.5] * 24
    null = [0.5] * 24
    live_errors = deque(maxlen=32)

    for i in range(1000):
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

        control.after_report(
            live, x, ctx, null, live_gain, mean_err, awake=True, entity_time_s=float(i)
        )

    return control.result()


def test_detection_end_to_end():
    result = _run_topos_detection(min_effect=0.02)
    assert result["processor"] == "topos"
    assert result["mode"] == "control"
    assert result["n_reports"] > 900
    assert result["detected"] is True
    assert result["noise_detected"] is False
    assert result["passed"] is True
    assert result["effect"] > 0.02
    assert result["ig_without"] == pytest.approx(0.0, abs=1e-9)


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
    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 100.0},
        min_effect=0.02,
        min_reports=1,
        t_learn_s=0.0,
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

    for i in range(200):
        x = rng.standard_normal(4).tolist()
        err_with = live_with.step(x, ctx, null)
        control.after_report(
            live_with, x, ctx, null, None, None, awake=True, entity_time_s=float(i)
        )
        err_without = live_without.step(x, ctx, null)

        errors_with.append(err_with)
        errors_without.append(err_without)
        nulls_with.append(live_with.last_null_error)
        nulls_without.append(live_without.last_null_error)

    assert errors_with == errors_without
    assert nulls_with == nulls_without
    _assert_state_equal(live_with.state_dict(), live_without.state_dict())


def test_asleep_reports_do_not_count():
    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 100.0},
        min_effect=0.01,
        min_reports=1,
        t_learn_s=0.0,
    )
    control = PositiveControl("topos", settings)
    live = LatentForwardModel(
        latent_dim=4, units=16, context_dim=24, seed=3, lr=0.05
    )

    rng = np.random.default_rng(13)
    ctx = [0.0] * 24
    null = [0.0] * 24

    for i in range(50):
        x = rng.standard_normal(4).tolist()
        live.step(x, ctx, null)
        ret = control.after_report(
            live, x, ctx, null, 0.0, 1.0, awake=False, entity_time_s=float(i)
        )
        assert ret is None

    result = control.result()
    assert result["n_reports"] == 0
    assert result["ig_with"] is None
    assert result["detected"] is None


@pytest.mark.asyncio
async def test_publish_result(bus):
    ladder_record = {
        "record": "ladder",
        "processor": "topos",
        "entity_time_s": 1.0,
        "gain": 0.1,
        "gain_with": [0.1] * len(SNR_LADDER),
        "gain_noise": [0.0] * len(SNR_LADDER),
        "snr": list(SNR_LADDER),
        "pc_sha256": "abc",
    }
    await publish_result(bus, ladder_record)

    entries = await bus.read("positive_control.out", last_id="0")
    assert len(entries) == 1
    entry_id, event = entries[0]
    assert isinstance(event, Event)
    assert event.source == POSITIVE_CONTROL_SOURCE
    assert event.type == LADDER_EVENT_TYPE
    assert "record" not in event.payload

    result = {
        "record": "result",
        "processor": "topos",
        "mode": "control",
        "n_reports": 10,
        "ig_with": 0.1,
        "ig_without": 0.0,
        "ig_noise": 0.0,
        "effect": 0.1,
        "noise_effect": 0.0,
        "min_effect": 0.02,
        "min_reports": 1,
        "snr": 100.0,
        "t_learn_s": 0.0,
        "settings_sha256": "settings-sha",
        "pc_sha256": "pc-sha",
        "detected": True,
        "noise_detected": False,
        "passed": True,
        "failed": False,
        "final": False,
    }
    await publish_result(bus, result)

    entries = await bus.read("positive_control.out", last_id="0")
    assert len(entries) == 2
    entry_id, event = entries[1]
    assert isinstance(event, Event)
    assert event.source == POSITIVE_CONTROL_SOURCE
    assert event.type == RESULT_EVENT_TYPE
    assert event.payload == {k: v for k, v in result.items() if k != "record"}


def test_constructor_rejects_unknown_processor():
    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 10.0},
        min_effect=0.01,
        min_reports=1,
        t_learn_s=0.0,
    )
    with pytest.raises(ValueError, match="processor"):
        PositiveControl("vision", settings)


def test_constructor_rejects_disabled():
    settings = PositiveControlSettings(enabled=False)
    with pytest.raises(ValueError, match="disabled"):
        PositiveControl("topos", settings)


def test_after_report_requires_model_methods():
    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 10.0},
        min_effect=0.01,
        min_reports=1,
        t_learn_s=0.0,
    )
    control = PositiveControl("topos", settings)

    class NoMethods:
        pass

    with pytest.raises(TypeError, match="topos"):
        control.after_report(
            NoMethods(), [0.0], None, None, None, None, awake=True, entity_time_s=0.0
        )


def test_non_informative_value_ignores_the_current_input():
    pc = _pc("topos", 4)
    source_a = ComponentSource(
        informative=False, snr=10.0, seed=7, processor="topos", slot=1, pc=pc
    )
    source_b = ComponentSource(
        informative=False, snr=10.0, seed=7, processor="topos", slot=1, pc=pc
    )
    shared = [[float(i), float(i + 1), float(i + 2), float(i + 3)] for i in range(20)]
    for x in shared:
        source_a.next(x)
        source_b.next(x)
    assert source_a.next([1.0, 2.0, 3.0, 4.0]) == source_b.next(
        [-50.0, 9.0, 0.0, 7.0]
    )

    fresh = ComponentSource(
        informative=False, snr=10.0, seed=9, processor="audition", slot=1, pc=_pc("audition", 3)
    )
    assert fresh.next([1.0, 2.0, 3.0]) == 0.0


def test_noise_depends_on_run_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Different run seeds draw independent noise; identical seeds replay it."""
    from types import SimpleNamespace

    from kaine.modules.positive_control import ComponentSource, PositiveControl

    pc = _pc("soma", 3)

    rng = np.random.default_rng(4)
    xs = rng.normal(size=(20, 3))

    a = ComponentSource(
        informative=False,
        snr=1.0,
        seed=0,
        processor="soma",
        slot=0,
        pc=pc,
        run_seed=1,
    )
    b = ComponentSource(
        informative=False,
        snr=1.0,
        seed=0,
        processor="soma",
        slot=0,
        pc=pc,
        run_seed=1,
    )
    c = ComponentSource(
        informative=False,
        snr=1.0,
        seed=0,
        processor="soma",
        slot=0,
        pc=pc,
        run_seed=2,
    )

    a_vals = np.array([a.next(x) for x in xs])
    b_vals = np.array([b.next(x) for x in xs])
    c_vals = np.array([c.next(x) for x in xs])

    assert np.array_equal(a_vals, b_vals)
    assert np.array_equal(a_vals[:2], c_vals[:2])
    assert not np.array_equal(a_vals[2:], c_vals[2:])

    monkeypatch.setattr(
        "kaine.modules.positive_control.get_run_context",
        lambda: SimpleNamespace(seed=7, run_id="r"),
    )
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"soma": pc},
        pc_sha256={"soma": "sha"},
        snr={"soma": 10.0},
        min_effect=0.01,
        min_reports=1,
        t_learn_s=0.0,
    )
    control = PositiveControl("soma", settings)
    assert control._run_seed == 7

    monkeypatch.setattr(
        "kaine.modules.positive_control.get_run_context",
        lambda: None,
    )
    control = PositiveControl("soma", settings)
    assert control._run_seed == 0


def test_gains_share_the_live_denominator():
    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 10.0},
        min_effect=0.01,
        min_reports=1,
        t_learn_s=0.0,
    )
    control = PositiveControl("topos", settings)
    control._probes[0].step = lambda *args, **kwargs: 0.2
    control._probes[1].step = lambda *args, **kwargs: 0.0

    class Model:
        def widened_copy(self, n):
            return self

        def hindsight_step(self, *args, **kwargs):
            return (0.0, 0.0)

    result = control.after_report(
        Model(), [0.0], None, None, 0.1, 2.0, awake=True, entity_time_s=1.0
    )
    assert result is not None
    assert result["ig_with"] == pytest.approx(0.1)
    assert result["ig_without"] == pytest.approx(0.1)
    assert result["ig_noise"] == pytest.approx(0.0)


def test_non_finite_gains_are_not_counted():
    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 10.0},
        min_effect=0.01,
        min_reports=1,
        t_learn_s=0.0,
    )
    control = PositiveControl("topos", settings)
    control._probes[0].step = lambda *args, **kwargs: 0.2
    control._probes[1].step = lambda *args, **kwargs: 0.0

    class Model:
        def widened_copy(self, n):
            return self

        def hindsight_step(self, *args, **kwargs):
            return (0.0, 0.0)

    model = Model()
    assert (
        control.after_report(
            model, [0.0], None, None, float("nan"), 2.0, awake=True, entity_time_s=0.0
        )
        is None
    )
    assert control.result()["n_reports"] == 0
    assert (
        control.after_report(
            model, [0.0], None, None, 0.1, 0.0, awake=True, entity_time_s=0.0
        )
        is None
    )
    assert control.result()["n_reports"] == 0


def test_final_and_failure_results():
    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 10.0},
        min_effect=0.01,
        min_reports=1,
        t_learn_s=0.0,
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
    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 100.0},
        min_effect=0.02,
        min_reports=100,
        t_learn_s=0.0,
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
            control.after_report(
                live, x, ctx, null, None, None, awake=True, entity_time_s=float(i)
            )
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
                live, x, ctx, null, live_gain, mean_err, awake=True, entity_time_s=float(i)
            )

    result = control.result()
    assert result["n_reports"] > 0
    assert math.isfinite(result["ig_with"])
    assert math.isfinite(result["ig_without"])
    assert math.isfinite(result["ig_noise"])
    assert math.isfinite(result["effect"])


def test_failure_result_cannot_pass():
    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 10.0},
        min_effect=0.01,
        min_reports=1,
        t_learn_s=0.0,
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
    pc = _pc(processor, 4, direction=np.array([1.0, 1.0, 1.0, 1.0]))
    shared = [[float(i), float(i + 1), float(i + 2), float(i + 3)] for i in range(20)]
    a = [1.0, 2.0, 3.0, 4.0]
    b = [-5.0, 0.5, 2.0, 1.0]

    src_a = ComponentSource(
        informative=True, snr=snr, seed=seed, processor=processor, slot=1, pc=pc
    )
    src_b = ComponentSource(
        informative=True, snr=snr, seed=seed, processor=processor, slot=1, pc=pc
    )

    for x in shared:
        src_a.next(x)
        src_b.next(x)

    out_a = src_a.next(a)
    out_b = src_b.next(b)

    expected = pc.project(a) - pc.project(b)
    assert out_a - out_b == pytest.approx(expected, abs=1e-9)

    src = ComponentSource(
        informative=True, snr=snr, seed=seed + 1, processor=processor, slot=1, pc=pc
    )
    x = [1.0, 2.0, 3.0, 4.0]
    out = src.next(x)
    assert out == pytest.approx(pc.project(x), abs=1e-9)


def test_t_learn_counts_only_after_initial_period():
    class CountingShadow:
        context_dim = 25

        def __init__(self):
            self.calls = 0

        def hindsight_step(self, x, ctx, null_ctx, **kwargs):
            self.calls += 1
            return (0.0, 0.0)

    class StubLive:
        def __init__(self):
            self.shadows = []

        def widened_copy(self, extra):
            shadow = CountingShadow()
            self.shadows.append(shadow)
            return shadow

        def hindsight_step(self, *args, **kwargs):
            raise AssertionError("the live model is never stepped in hindsight")

    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="control",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
        snr={"topos": 100.0},
        min_effect=0.01,
        min_reports=1,
        t_learn_s=50.0,
    )
    control = PositiveControl("topos", settings)
    live = StubLive()
    control.prepare(live)

    for i in range(1, 101):
        ret = control.after_report(
            live,
            [0.0] * 4,
            [0.0] * 24,
            [0.0] * 24,
            0.1,
            1.0,
            awake=True,
            entity_time_s=float(i),
        )
        if i > 50:
            assert ret is not None

    result = control.result()
    assert result["mode"] == "control"
    assert result["n_reports"] == 50
    total_calls = sum(shadow.calls for shadow in live.shadows)
    # The first report only stores the baseline context, so each shadow is stepped 99 times.
    assert total_calls == 99 * 2


def test_ladder_returns_gains_for_every_rung():
    class StubShadow:
        context_dim = 25

        def hindsight_step(self, x, ctx, null_ctx, **kwargs):
            return (0.0, 0.0)

    class StubLive:
        def __init__(self):
            self.shadows = []

        def widened_copy(self, extra):
            shadow = StubShadow()
            self.shadows.append(shadow)
            return shadow

        def hindsight_step(self, *args, **kwargs):
            raise AssertionError("the live model is never stepped in hindsight")

    pc = _pc("topos", 4)
    settings = PositiveControlSettings(
        enabled=True,
        mode="ladder",
        seed=0,
        principal_components={"topos": pc},
        pc_sha256={"topos": "sha"},
    )
    control = PositiveControl("topos", settings)
    live = StubLive()
    control.prepare(live)

    assert len(control._probes) == 14

    # First call stores the baseline context.
    assert (
        control.after_report(
            live,
            [0.0] * 4,
            [0.0] * 24,
            [0.0] * 24,
            0.1,
            1.0,
            awake=True,
            entity_time_s=1.0,
        )
        is None
    )

    record = control.after_report(
        live,
        [0.0] * 4,
        [0.0] * 24,
        [0.0] * 24,
        0.1,
        1.0,
        awake=True,
        entity_time_s=2.0,
    )
    assert record["record"] == "ladder"
    assert record["processor"] == "topos"
    assert record["entity_time_s"] == 2.0
    assert len(record["gain_with"]) == len(SNR_LADDER)
    assert len(record["gain_noise"]) == len(SNR_LADDER)
    assert record["snr"] == list(SNR_LADDER)
    assert record["pc_sha256"] == "sha"

    result = control.result()
    assert result["mode"] == "ladder"
    assert result["n_reports"] == 1


def test_estimate_pc_records_principal_component(tmp_path, monkeypatch):
    # Provide a seed because PositiveControl now reads the run context seed.
    monkeypatch.setattr(
        "kaine.modules.positive_control.get_run_context",
        type("RC", (), {"run_id": "prelim", "seed": 0}),
    )

    rng = np.random.default_rng(21)
    dim = 4
    v = np.array([1.0, 2.0, 3.0, 4.0])
    v /= np.linalg.norm(v)
    settings = PositiveControlSettings(
        enabled=True,
        mode="estimate_pc",
        seed=0,
        pc_root=str(tmp_path),
    )
    control = PositiveControl("topos", settings)

    for i in range(500):
        z = rng.standard_normal()
        x = 5.0 * z * v + 0.1 * rng.standard_normal(dim)
        control.after_report(
            None, x.tolist(), None, None, None, None, awake=True, entity_time_s=float(i)
        )

    for i in range(10):
        x = rng.standard_normal(dim)
        control.after_report(
            None,
            x.tolist(),
            None,
            None,
            None,
            None,
            awake=False,
            entity_time_s=float(500 + i),
        )

    control.after_report(
        None,
        [float("nan")] * dim,
        None,
        None,
        None,
        None,
        awake=True,
        entity_time_s=511.0,
    )

    result = control.final_result()
    assert result["mode"] == "estimate_pc"
    assert result["n_reports"] == 500
    assert result["final"] is True

    written_path = principal_component_path(tmp_path, "prelim", "topos")
    assert result["pc_sha256"] == file_sha256(written_path)

    loaded = load_principal_component(
        written_path, expected_sha256=result["pc_sha256"]
    )
    direction = np.array(loaded.direction)
    assert abs(np.dot(direction, v)) > 0.99


def test_estimate_pc_requires_run_context():
    settings = PositiveControlSettings(
        enabled=True, mode="estimate_pc", seed=0
    )
    control = PositiveControl("topos", settings)
    with pytest.raises(PrincipalComponentError, match="run context"):
        control.final_result()


@pytest.mark.asyncio
async def test_control_queue_runs_jobs_in_order():
    import asyncio

    from kaine.modules.positive_control import ControlQueue

    queue = ControlQueue()
    results: list[int] = []

    async def make_job(n: int) -> None:
        await asyncio.sleep(0)
        results.append(n)

    for i in range(5):
        assert queue.submit(lambda i=i: make_job(i)) is True

    await queue.drain()
    assert results == list(range(5))

    await queue.close()
    assert queue.submit(lambda: make_job(99)) is True
    await queue.drain()
    assert results[-1] == 99
    await queue.close()


@pytest.mark.asyncio
async def test_control_queue_refuses_at_max_pending():
    import asyncio

    from kaine.modules.positive_control import ControlQueue

    queue = ControlQueue(max_pending=2)
    event = asyncio.Event()

    async def wait_job() -> None:
        await event.wait()

    assert queue.submit(wait_job) is True
    assert queue.submit(wait_job) is True
    assert queue.submit(wait_job) is False

    event.set()
    await queue.drain()
    await queue.close()


@pytest.mark.asyncio
async def test_control_queue_exception_continues(caplog):
    import logging

    from kaine.modules.positive_control import ControlQueue

    queue = ControlQueue()
    ran: list[int] = []

    async def bad_job() -> None:
        raise RuntimeError("control job failed")

    async def good_job() -> None:
        ran.append(1)

    with caplog.at_level(logging.ERROR):
        assert queue.submit(bad_job) is True
        assert queue.submit(good_job) is True
        await queue.drain()

    assert ran == [1]
    assert "control job failed" in caplog.text
    await queue.close()


def test_shadow_probe_step_uses_suspended_override():
    """The shadow's suspended flag follows the value captured at the report when given."""

    class StubShadow:
        context_dim = 25

        def __init__(self) -> None:
            self.suspended = False

        def hindsight_step(self, x, ctx, null_ctx, **kwargs):
            return (1.0, 1.0)

    class StubLive:
        suspended = False

        def widened_copy(self, extra):
            return StubShadow()

        def hindsight_step(self, *args, **kwargs):
            raise AssertionError("the live model is never stepped in hindsight")

    pc = _pc("topos", 2)
    probe = ShadowProbe(
        ComponentSource(informative=True, snr=1.0, seed=0, processor="topos", slot=0, pc=pc)
    )
    live = StubLive()
    ctx = [0.0] * 24
    probe.step(live, [0.0, 0.0], ctx, ctx)  # the first step only stores the baseline
    probe.step(live, [1.0, 0.0], ctx, ctx, suspended=True)
    assert probe._shadow.suspended is True

    live.suspended = True
    probe.step(live, [0.5, 0.0], ctx, ctx, suspended=False)
    assert probe._shadow.suspended is False

    probe.step(live, [0.2, 0.0], ctx, ctx)
    assert probe._shadow.suspended is True
