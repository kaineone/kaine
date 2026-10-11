# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Wiring tests for the positive-control shadow of the information-gain measure."""

from __future__ import annotations

import math
import random
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import torch

import kaine.modules.topos.module as topos_module
from kaine.boot import make_soma
from kaine.boot.registry import construct_module
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.evaluation.config import EvaluationConfig, ResearchEventLogConfig
from kaine.evaluation.registry import SidecarRegistry
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.experiment.run_records import load_run_records
from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.acoustic import FakeAcousticEncoder
from kaine.modules.base import BaseModule
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.positive_control import (
    RESULT_FIELDS,
    PositiveControlSettings,
    finish_positive_controls,
)
from kaine.modules.registry import ModuleRegistry
from kaine.modules.soma.detector import AlertResult
from kaine.modules.soma.forward import SubstrateForwardModel
from kaine.modules.soma.module import Soma
from kaine.modules.topos.forward import LatentForwardModel


def _bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


@pytest.fixture
async def bus():
    bus = _bus()
    yield bus
    await bus.close()


def _workspace(source: str, salience: float, score: float) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            (
                "1-0",
                Event(
                    source=source,
                    type=f"{source}.report",
                    payload={"k": 1},
                    salience=salience,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=False,
        salience_scores={"1-0": score},
        metadata={"access_threshold": 0.35},
    )


def _payloads(events):
    out = []
    for ev in events:
        if isinstance(ev, tuple):
            ev = ev[-1]
        if hasattr(ev, "payload"):
            out.append(ev.payload)
        elif isinstance(ev, dict) and "payload" in ev:
            out.append(ev["payload"])
        else:
            out.append(ev)
    return out


def _tone(freq: float, seconds: float = 0.2, amp: float = 0.3, sr: int = 16000) -> bytes:
    samples = np.arange(int(sr * seconds))
    wave = (amp * np.sin(2.0 * np.pi * freq * samples / sr) * 32767).astype(np.int16)
    return wave.tobytes()


async def _reports(bus: AsyncBus, stream: str = "topos.out") -> list[dict]:
    return _payloads(await bus.read(stream, last_id="0"))


class _FixedClock:
    """Entity clock frozen in time, so both instances see the same context age."""

    def now(self) -> float:
        return 100.0


class Varying:
    model_id = "fake/varying"
    latent_dim = 4
    clip_len = 1

    def __init__(self) -> None:
        self._counter = 0

    async def load(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def encode(self, image):  # noqa: ARG002
        k = self._counter
        self._counter += 1
        return [math.sin(k), math.cos(k), math.sin(2 * k), math.cos(3 * k)]

    async def encode_clip(self, frames):
        return await self.encode(frames[-1])


class FakeMetricsReader:
    def __init__(self, metrics: dict[str, float] | None = None) -> None:
        self._metrics = metrics or {"cpu_percent": 10.0, "ram_percent": 20.0}
        self.latencies: list[float] = []
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def read_metrics(self) -> dict[str, float]:
        out = dict(self._metrics)
        if self.latencies:
            out["cycle_latency_avg_ms"] = sum(self.latencies) / len(self.latencies)
        return out

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        self.latencies.append(float(wall_duration_ms))


class NeverAlertDetector:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:  # noqa: ARG002
        return AlertResult()


def _rng_states_equal(a, b):
    assert a[0] == b[0]
    assert np.array_equal(a[1], b[1])
    assert a[2:] == b[2:]


def test_shipped_config_leaves_the_control_off():
    path = Path(__file__).resolve().parents[1] / "config" / "kaine.toml"
    with path.open("rb") as fh:
        config = tomllib.load(fh)
    pc = config["positive_control"]
    assert pc["enabled"] is False
    assert "min_effect" not in pc
    assert "min_reports" not in pc
    assert "snr" not in pc


def test_soma_factory_builds_the_control_only_when_enabled():
    bus = _bus()
    assert make_soma(bus, {})._positive_control is None
    controlled = make_soma(
        bus,
        {"positive_control": {"enabled": True, "snr": 10.0, "min_effect": 0.01, "min_reports": 1}},
    )
    from kaine.modules.positive_control import PositiveControl

    assert isinstance(controlled._positive_control, PositiveControl)
    with pytest.raises(ValueError):
        make_soma(bus, {"positive_control": {"enabled": True}})


def test_construct_module_passes_the_section():
    bus = _bus()
    module = construct_module(
        "soma",
        bus,
        {
            "soma": {},
            "positive_control": {"enabled": True, "snr": 5.0, "min_effect": 0.01, "min_reports": 1},
        },
        registry=ModuleRegistry(),
    )
    assert isinstance(module, BaseModule)
    assert module._positive_control is not None


@pytest.mark.asyncio
async def test_topos_control_publishes_and_leaves_the_live_report_untouched() -> None:
    uncontrolled_bus = _bus()
    controlled_bus = _bus()

    uncontrolled = topos_module.Topos(
        uncontrolled_bus,
        encoder=Varying(),
        forward_prediction=True,
        entity_clock=_FixedClock(),
    )
    uncontrolled._forward_model = LatentForwardModel(
        latent_dim=4,
        units=8,
        context_dim=CONTEXT_DIM,
        seed=4,
    )

    controlled = topos_module.Topos(
        controlled_bus,
        encoder=Varying(),
        forward_prediction=True,
        entity_clock=_FixedClock(),
        positive_control=PositiveControlSettings(enabled=True, snr=10.0, min_effect=0.01, min_reports=1),
    )
    controlled._forward_model = LatentForwardModel(
        latent_dim=4,
        units=8,
        context_dim=CONTEXT_DIM,
        seed=4,
    )

    await uncontrolled.on_workspace(_workspace("soma", 0.6, 0.6))
    await controlled.on_workspace(_workspace("soma", 0.6, 0.6))

    for i in range(8):
        if i == 3:
            await uncontrolled.on_workspace(_workspace("thymos", 0.75, 0.75))
            await controlled.on_workspace(_workspace("thymos", 0.75, 0.75))
        await uncontrolled.process_frame(None)
        await controlled.process_frame(None)

    un_reports = await _reports(uncontrolled_bus, "topos.out")
    co_reports = await _reports(controlled_bus, "topos.out")

    assert len(un_reports) == len(co_reports)
    for a, b in zip(un_reports, co_reports):
        for key in (
            "prediction_error",
            "context_gain",
            "null_prediction_error",
            "mean_prediction_error",
        ):
            assert a[key] == b[key]

    pc_events = await controlled_bus.read("positive_control.out", last_id="0")
    assert pc_events
    pc_payloads = _payloads(pc_events)
    assert any(p.get("processor") == "topos" for p in pc_payloads)
    for p in pc_payloads:
        if p.get("processor") == "topos":
            assert set(p.keys()) == set(RESULT_FIELDS)
            break

    assert await uncontrolled_bus.read("positive_control.out", last_id="0") == []
    await uncontrolled_bus.close()
    await controlled_bus.close()


@pytest.mark.asyncio
async def test_soma_control_publishes_results(bus: AsyncBus) -> None:
    soma = Soma(
        bus,
        reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
        detector=NeverAlertDetector(),
        # Built directly, not from config, to check that no verdict is recorded
        # without a minimum effect.
        positive_control=PositiveControlSettings(enabled=True, snr=10.0),
    )
    await soma.on_workspace(_workspace("topos", 0.7, 0.5))
    for _ in range(6):
        await soma.tick_once()

    events = await bus.read("positive_control.out", last_id="0")
    assert events
    payloads = _payloads(events)
    assert all(p.get("processor") == "soma" for p in payloads)
    assert all(p.get("passed") is None for p in payloads)


@pytest.mark.asyncio
async def test_failing_control_switches_itself_off(bus: AsyncBus) -> None:
    topos = topos_module.Topos(
        bus,
        encoder=Varying(),
        forward_prediction=True,
        positive_control=PositiveControlSettings(enabled=True, snr=10.0, min_effect=0.01, min_reports=1),
    )
    topos._forward_model = LatentForwardModel(
        latent_dim=4,
        units=8,
        context_dim=CONTEXT_DIM,
        seed=4,
    )

    def _raise(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("control failure")

    topos._positive_control.after_report = _raise

    await topos.on_workspace(_workspace("soma", 0.6, 0.6))
    for _ in range(3):
        await topos.process_frame(None)

    assert topos._positive_control is None
    assert len(await _reports(bus, "topos.out")) == 3
    positive_reports = await _reports(bus, "positive_control.out")
    assert len(positive_reports) == 1
    assert positive_reports[0]["failed"] is True
    assert positive_reports[0]["passed"] is False
    assert positive_reports[0]["processor"] == "topos"
    assert positive_reports[0]["final"] is True


@pytest.mark.asyncio
async def test_shutdown_publishes_a_terminal_record() -> None:
    bus = _bus()
    try:
        topos = topos_module.Topos(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=PositiveControlSettings(enabled=True, snr=10.0, min_effect=0.01, min_reports=1),
        )
        topos._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )

        await topos.on_workspace(_workspace("soma", 0.6, 0.6))
        for _ in range(5):
            await topos.process_frame(None)
        await topos.shutdown()

        events = await bus.read("positive_control.out", last_id="0")
        assert events
        payload = _payloads(events)[-1]
        assert payload["processor"] == "topos"
        assert payload["final"] is True
        assert payload["failed"] is False
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_soma_shutdown_publishes_a_terminal_record() -> None:
    bus = _bus()
    try:
        soma = Soma(
            bus,
            reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
            detector=NeverAlertDetector(),
            positive_control=PositiveControlSettings(enabled=True, snr=10.0, min_effect=0.01, min_reports=1),
        )
        await soma.on_workspace(_workspace("topos", 0.7, 0.5))
        for _ in range(6):
            await soma.tick_once()
        await soma.shutdown()

        events = await bus.read("positive_control.out", last_id="0")
        assert events
        payload = _payloads(events)[-1]
        assert payload["processor"] == "soma"
        assert payload["final"] is True
        assert payload["failed"] is False
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_unpublishable_failure_is_logged_at_error(bus: AsyncBus, caplog) -> None:
    topos = topos_module.Topos(
        bus,
        encoder=Varying(),
        forward_prediction=True,
        positive_control=PositiveControlSettings(enabled=True, snr=10.0, min_effect=0.01, min_reports=1),
    )
    topos._forward_model = LatentForwardModel(
        latent_dim=4,
        units=8,
        context_dim=CONTEXT_DIM,
        seed=4,
    )

    def _raise(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("control failure")

    async def _raise_publish(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("publish failure")

    topos._positive_control.after_report = _raise
    original_publish = topos_module.publish_result
    topos_module.publish_result = _raise_publish

    try:
        await topos.on_workspace(_workspace("soma", 0.6, 0.6))
        for _ in range(3):
            await topos.process_frame(None)
    finally:
        topos_module.publish_result = original_publish

    assert topos._positive_control is None
    assert await _reports(bus, "positive_control.out") == []
    error_messages = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert any("cannot pass" in m for m in error_messages)


async def _topos_run(control_settings):
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    bus = _bus()
    try:
        topos = topos_module.Topos(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=control_settings,
        )
        topos._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )
        await topos.on_workspace(_workspace("soma", 0.6, 0.6))
        for i in range(12):
            if i == 6:
                await topos.on_workspace(_workspace("thymos", 0.75, 0.75))
            await topos.process_frame(None)
        return (
            topos._forward_model.state_dict(),
            random.getstate(),
            np.random.get_state(),
            torch.get_rng_state(),
        )
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_topos_control_leaves_live_weights_and_rng_states_identical() -> None:
    off = await _topos_run(None)
    on = await _topos_run(
        PositiveControlSettings(enabled=True, snr=10.0, min_effect=0.01, min_reports=1)
    )

    assert off[0] == on[0]
    _rng_states_equal(off[1], on[1])
    _rng_states_equal(off[2], on[2])
    assert torch.equal(off[3], on[3])


class _SteppingClock:
    """Entity clock that advances a fixed step per reading, so both runs see the same times."""

    def __init__(self) -> None:
        self._t = 0.0

    def now(self) -> float:
        self._t += 0.5
        return self._t


async def _soma_run(control_settings):
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    bus = _bus()
    try:
        soma = Soma(
            bus,
            reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
            detector=NeverAlertDetector(),
            entity_clock=_SteppingClock(),
            positive_control=control_settings,
        )
        soma._forward_model = SubstrateForwardModel(
            feature_dim=8,
            units=16,
            seed=5,
            context_dim=CONTEXT_DIM,
        )
        await soma.on_workspace(_workspace("topos", 0.7, 0.5))
        for _ in range(12):
            await soma.tick_once()
        return (
            soma._forward_model.state_dict(),
            random.getstate(),
            np.random.get_state(),
            torch.get_rng_state(),
        )
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_soma_control_leaves_live_weights_and_rng_states_identical() -> None:
    off = await _soma_run(None)
    on = await _soma_run(
        PositiveControlSettings(enabled=True, snr=10.0, min_effect=0.01, min_reports=1)
    )

    assert off[0] == on[0]
    _rng_states_equal(off[1], on[1])
    _rng_states_equal(off[2], on[2])
    assert torch.equal(off[3], on[3])


async def _audition_run(control_settings):
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    bus = _bus()
    try:
        audition = Audition(
            bus,
            stt_client=FakeSTTClient(responses=["x"]),
            emotion_classifier=FakeEmotionClassifier(),
            stt_model="fake-stt",
            general_audition=True,
            acoustic_encoder=FakeAcousticEncoder(embedding_dim=8),
            entity_clock=_FixedClock(),
            positive_control=control_settings,
        )
        await audition.initialize()
        await audition.on_workspace(_workspace("soma", 0.6, 0.6))
        for i, freq in enumerate(range(4000, 9000, 500)):
            if i == 5:
                await audition.on_workspace(_workspace("thymos", 0.75, 0.75))
            await audition.process_audio(_tone(freq), sample_rate=16000)
        return (
            audition._acoustic_forward_model.state_dict(),
            random.getstate(),
            np.random.get_state(),
            torch.get_rng_state(),
        )
    finally:
        await audition.shutdown()
        await bus.close()


@pytest.mark.asyncio
async def test_audition_control_leaves_live_weights_and_rng_states_identical() -> None:
    off = await _audition_run(None)
    on = await _audition_run(
        PositiveControlSettings(enabled=True, snr=10.0, min_effect=0.01, min_reports=1)
    )

    assert off[0] == on[0]
    _rng_states_equal(off[1], on[1])
    _rng_states_equal(off[2], on[2])
    assert torch.equal(off[3], on[3])


@pytest.mark.asyncio
async def test_terminal_record_reaches_the_research_log(tmp_path) -> None:
    set_run_context(
        RunContext(
            run_id="run-pc",
            seed=1,
            started_at="2026-10-10T00:00:00+00:00",
            git_sha=None,
        )
    )
    bus = _bus()
    try:
        sidecar = SidecarRegistry(
            bus=bus,
            config=EvaluationConfig.from_mapping({"enabled": False}),
            research_event_log_config=ResearchEventLogConfig(
                enabled=True, log_dir=str(tmp_path / "research_events")
            ),
        )
        sidecar.build()
        await sidecar.start()

        topos = topos_module.Topos(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=PositiveControlSettings(
                enabled=True, snr=10.0, min_effect=0.01, min_reports=1
            ),
        )
        topos._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )

        await topos.on_workspace(_workspace("soma", 0.6, 0.6))
        for _ in range(6):
            await topos.process_frame(None)

        await finish_positive_controls([topos])
        await sidecar.stop()
        await topos.shutdown()

        run = load_run_records("run-pc", root=tmp_path)
        pc_records = [
            rec
            for _, rec in run.all_records()
            if rec.get("event_type") == "positive_control.result"
            and rec.get("processor") == "topos"
        ]
        assert pc_records
        assert pc_records[-1]["final"] is True
        assert pc_records[-1]["failed"] is False
        assert sum(1 for r in pc_records if r.get("final") is True) == 1
    finally:
        set_run_context(None)
        await bus.close()


class _VaryingWithGap(Varying):
    """Varying latents, with a non-finite one at report 5."""

    async def encode(self, image):
        k = self._counter
        vec = await super().encode(image)
        return [float("nan")] * 4 if k == 5 else vec


@pytest.mark.asyncio
async def test_topos_control_stays_paired_across_a_skip():
    """After a non-finite latent is skipped, the shadow forward models stay
    paired with the live forward model and resume together."""
    bus = _bus()
    try:
        topos = topos_module.Topos(
            bus,
            encoder=_VaryingWithGap(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=PositiveControlSettings(
                enabled=True, snr=10.0, min_effect=0.01, min_reports=1
            ),
        )
        topos._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )
        await topos.on_workspace(_workspace("soma", 0.6, 0.6))
        control = topos._positive_control

        for i in range(10):
            if i == 3:
                await topos.on_workspace(_workspace("thymos", 0.75, 0.75))
            await topos.process_frame(None)
            for probe in (control._probe_info, control._probe_noise):
                assert [
                    list(v) for v in probe._shadow._buffer
                ] == [list(v) for v in topos._forward_model._buffer]

        reports = await _reports(bus, "topos.out")
        gains = [r["context_gain"] for r in reports]
        assert gains[5] is None
        assert gains[6] is None
        assert isinstance(gains[7], float)
        assert control._n == sum(1 for g in gains if g is not None)

        for p in _payloads(await bus.read("positive_control.out", last_id="0")):
            for v in p.values():
                if isinstance(v, float):
                    assert math.isfinite(v)
    finally:
        await bus.close()
