# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Wiring tests for the positive-control shadow of the information-gain measure."""

from __future__ import annotations

import asyncio
import math
import random
import threading
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import torch

import kaine.modules.vision.module as vision_module
from kaine.boot import make_interoception
from kaine.boot.registry import construct_module
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.evaluation.config import EvaluationConfig, ResearchEventLogConfig
from kaine.evaluation.observers.research_event_observer import _apply_taxonomy_fields
from kaine.evaluation.registry import SidecarRegistry
from kaine.experiment.principal_component import PrincipalComponent
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.experiment.run_records import load_run_records
from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.acoustic import FakeAcousticEncoder
from kaine.modules.base import BaseModule
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.interoception.detector import AlertResult
from kaine.modules.interoception.forward import SubstrateForwardModel
from kaine.modules.interoception.module import Interoception
from kaine.modules.positive_control import (
    LADDER_FIELDS,
    RESULT_FIELDS,
    ControlQueue,
    PositiveControlSettings,
    finish_positive_controls,
)
from kaine.modules.registry import ModuleRegistry
from kaine.modules.vision.forward import LatentForwardModel


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


def _pc(processor: str, dim: int) -> PrincipalComponent:
    return PrincipalComponent(
        processor=processor,
        run_id="prelim",
        n_inputs=100,
        dim=dim,
        mean=tuple(0.0 for _ in range(dim)),
        direction=tuple(1.0 if i == 0 else 0.0 for i in range(dim)),
        variance=1.0,
        total_variance=float(dim),
    )


def _control(dims: dict[str, int], **overrides) -> PositiveControlSettings:
    settings = {
        "enabled": True,
        "mode": "control",
        "principal_components": {p: _pc(p, d) for p, d in dims.items()},
        "pc_sha256": {p: "0" * 64 for p in dims},
        "snr": {p: 10.0 for p in dims},
        "min_effect": 0.01,
        "min_reports": 1,
        "t_learn_s": 0.0,
        "settings_sha256": "1" * 64,
    }
    settings.update(overrides)
    return PositiveControlSettings(**settings)


def test_shipped_config_leaves_the_control_off():
    path = Path(__file__).resolve().parents[1] / "config" / "kaine.toml"
    with path.open("rb") as fh:
        config = tomllib.load(fh)
    pc = config["positive_control"]
    assert pc["enabled"] is False
    assert "min_effect" not in pc
    assert "min_reports" not in pc
    assert "snr" not in pc


def test_interoception_factory_builds_the_control_only_when_enabled():
    bus = _bus()
    assert make_interoception(bus, {})._positive_control is None
    controlled = make_interoception(
        bus,
        {"positive_control": {"enabled": True, "mode": "estimate_pc"}},
    )
    from kaine.modules.positive_control import PositiveControl

    assert isinstance(controlled._positive_control, PositiveControl)
    with pytest.raises(ValueError):
        make_interoception(bus, {"positive_control": {"enabled": True}})
    with pytest.raises(ValueError):
        make_interoception(bus, {"positive_control": {"enabled": True, "snr": 10.0}})


def test_construct_module_passes_the_section():
    bus = _bus()
    module = construct_module(
        "soma",
        bus,
        {
            "soma": {},
            "positive_control": {"enabled": True, "mode": "estimate_pc"},
        },
        registry=ModuleRegistry(),
    )
    assert isinstance(module, BaseModule)
    assert module._positive_control is not None


@pytest.mark.asyncio
async def test_vision_control_publishes_and_leaves_the_live_report_untouched() -> None:
    uncontrolled_bus = _bus()
    controlled_bus = _bus()

    uncontrolled = vision_module.Vision(
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

    controlled = vision_module.Vision(
        controlled_bus,
        encoder=Varying(),
        forward_prediction=True,
        entity_clock=_FixedClock(),
        positive_control=_control({"topos": 4}),
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

    # Wait for all queued control steps before inspecting their results.
    await controlled._pc_queue.drain()
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
async def test_interoception_control_publishes_results(bus: AsyncBus) -> None:
    interoception = Interoception(
        bus,
        reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
        detector=NeverAlertDetector(),
        # Built directly, not from config, to check the payload shape in control
        # mode. In control mode the minimum effect comes from the settings
        # record, so every tick records a verdict.
        positive_control=_control({"soma": 8}),
    )
    await interoception.on_workspace(_workspace("topos", 0.7, 0.5))
    for _ in range(6):
        await interoception.tick_once()

    # Wait for all queued control steps before inspecting their results.
    await interoception._pc_queue.drain()
    events = await bus.read("positive_control.out", last_id="0")
    assert events
    payloads = _payloads(events)
    assert all(p.get("processor") == "soma" for p in payloads)
    assert all(p.get("mode") == "control" for p in payloads)
    assert all(p.get("min_effect") == 0.01 for p in payloads)
    assert all(p.get("min_reports") == 1 for p in payloads)
    assert all(isinstance(p.get("passed"), bool) for p in payloads)


@pytest.mark.asyncio
async def test_failing_control_switches_itself_off(bus: AsyncBus) -> None:
    vision = vision_module.Vision(
        bus,
        encoder=Varying(),
        forward_prediction=True,
        positive_control=_control({"topos": 4}),
    )
    vision._forward_model = LatentForwardModel(
        latent_dim=4,
        units=8,
        context_dim=CONTEXT_DIM,
        seed=4,
    )

    def _raise(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("control failure")

    vision._positive_control.after_report = _raise

    await vision.on_workspace(_workspace("soma", 0.6, 0.6))
    for _ in range(3):
        await vision.process_frame(None)

    # The failure is handled asynchronously on the control queue.
    await vision._pc_queue.drain()
    assert vision._positive_control is None
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
        vision = vision_module.Vision(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=_control({"topos": 4}),
        )
        vision._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )

        await vision.on_workspace(_workspace("soma", 0.6, 0.6))
        for _ in range(5):
            await vision.process_frame(None)
        await vision.shutdown()

        events = await bus.read("positive_control.out", last_id="0")
        assert events
        payload = _payloads(events)[-1]
        assert payload["processor"] == "topos"
        assert payload["final"] is True
        assert payload["failed"] is False
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_interoception_shutdown_publishes_a_terminal_record() -> None:
    bus = _bus()
    try:
        interoception = Interoception(
            bus,
            reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
            detector=NeverAlertDetector(),
            positive_control=_control({"soma": 8}),
        )
        await interoception.on_workspace(_workspace("topos", 0.7, 0.5))
        for _ in range(6):
            await interoception.tick_once()
        await interoception.shutdown()

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
    vision = vision_module.Vision(
        bus,
        encoder=Varying(),
        forward_prediction=True,
        positive_control=_control({"topos": 4}),
    )
    vision._forward_model = LatentForwardModel(
        latent_dim=4,
        units=8,
        context_dim=CONTEXT_DIM,
        seed=4,
    )

    def _raise(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("control failure")

    async def _raise_publish(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("publish failure")

    vision._positive_control.after_report = _raise
    original_publish = vision_module.publish_result
    vision_module.publish_result = _raise_publish

    try:
        await vision.on_workspace(_workspace("soma", 0.6, 0.6))
        for _ in range(3):
            await vision.process_frame(None)
    finally:
        vision_module.publish_result = original_publish

    # The failure is handled asynchronously on the control queue.
    await vision._pc_queue.drain()
    assert vision._positive_control is None
    assert await _reports(bus, "positive_control.out") == []
    error_messages = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert any("cannot pass" in m for m in error_messages)


async def _vision_run(control_settings):
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    bus = _bus()
    try:
        vision = vision_module.Vision(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=control_settings,
        )
        vision._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )
        await vision.on_workspace(_workspace("soma", 0.6, 0.6))
        for i in range(12):
            if i == 6:
                await vision.on_workspace(_workspace("thymos", 0.75, 0.75))
            await vision.process_frame(None)
        return (
            vision._forward_model.state_dict(),
            random.getstate(),
            np.random.get_state(),
            torch.get_rng_state(),
        )
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_vision_control_leaves_live_weights_and_rng_states_identical() -> None:
    off = await _vision_run(None)
    on = await _vision_run(_control({"topos": 4}))

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


async def _interoception_run(control_settings):
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    bus = _bus()
    try:
        interoception = Interoception(
            bus,
            reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
            detector=NeverAlertDetector(),
            entity_clock=_SteppingClock(),
            positive_control=control_settings,
        )
        interoception._forward_model = SubstrateForwardModel(
            feature_dim=8,
            units=16,
            seed=5,
            context_dim=CONTEXT_DIM,
        )
        await interoception.on_workspace(_workspace("topos", 0.7, 0.5))
        for _ in range(12):
            await interoception.tick_once()
        return (
            interoception._forward_model.state_dict(),
            random.getstate(),
            np.random.get_state(),
            torch.get_rng_state(),
        )
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_interoception_control_leaves_live_weights_and_rng_states_identical() -> None:
    off = await _interoception_run(None)
    on = await _interoception_run(_control({"soma": 8}))

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
    on = await _audition_run(_control({"audition": 8}))

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

        vision = vision_module.Vision(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=_control({"topos": 4}),
        )
        vision._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )

        await vision.on_workspace(_workspace("soma", 0.6, 0.6))
        for _ in range(6):
            await vision.process_frame(None)

        await finish_positive_controls([vision])
        await sidecar.stop()
        await vision.shutdown()

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
        assert pc_records[-1]["mode"] == "control"
        assert pc_records[-1]["t_learn_s"] == 0.0
        assert sum(1 for r in pc_records if r.get("final") is True) == 1
    finally:
        set_run_context(None)
        await bus.close()


@pytest.mark.asyncio
async def test_vision_report_carries_entity_time_and_awake() -> None:
    bus = _bus()
    try:
        clock = _FixedClock()
        vision = vision_module.Vision(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=clock,
        )
        vision._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )

        await vision.on_workspace(_workspace("soma", 0.6, 0.6))
        await vision.process_frame(None)

        reports = await _reports(bus, "topos.out")
        assert reports
        assert reports[0]["entity_time_s"] == clock.now()
        assert reports[0]["awake"] is True

        vision._in_hypnos = True
        await vision.process_frame(None)
        reports = await _reports(bus, "topos.out")
        assert reports[-1]["awake"] is False
    finally:
        await bus.close()


def test_research_observer_keeps_ladder_fields() -> None:
    payload = {field: 0.0 for field in LADDER_FIELDS}
    payload["processor"] = "topos"
    payload["pc_sha256"] = "0" * 64
    payload["x"] = "extra"
    result = _apply_taxonomy_fields("positive_control.ladder", payload, {})
    assert set(LADDER_FIELDS).issubset(result.keys())
    assert "x" not in result


class _VaryingWithGap(Varying):
    """Varying latents, with a non-finite one at report 5."""

    async def encode(self, image):
        k = self._counter
        vec = await super().encode(image)
        return [float("nan")] * 4 if k == 5 else vec


@pytest.mark.asyncio
async def test_vision_control_stays_paired_across_a_skip():
    """After a non-finite latent is skipped, the shadow forward models stay
    paired with the live forward model and resume together."""
    bus = _bus()
    try:
        vision = vision_module.Vision(
            bus,
            encoder=_VaryingWithGap(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=_control({"topos": 4}),
        )
        vision._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )
        await vision.on_workspace(_workspace("soma", 0.6, 0.6))
        control = vision._positive_control

        for i in range(10):
            if i == 3:
                await vision.on_workspace(_workspace("thymos", 0.75, 0.75))
            await vision.process_frame(None)
            # Drain the queued control step before comparing shadow and live state.
            await vision._pc_queue.drain()
            for probe in control._probes:
                assert [
                    list(v) for v in probe._shadow._buffer
                ] == [list(v) for v in vision._forward_model._buffer]

        reports = await _reports(bus, "topos.out")
        gains = [r["context_gain"] for r in reports]
        assert gains[5] is None
        assert gains[6] is None
        assert isinstance(gains[7], float)
        assert control._n == sum(1 for g in gains if g is not None)

        await vision._pc_queue.drain()
        for p in _payloads(await bus.read("positive_control.out", last_id="0")):
            for v in p.values():
                if isinstance(v, float):
                    assert math.isfinite(v)
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_report_is_published_before_positive_control_steps() -> None:
    """The live report reaches the bus while the queued control step is still blocked."""
    bus = _bus()
    try:
        vision = vision_module.Vision(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=_control({"topos": 4}),
        )
        vision._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )
        await vision.on_workspace(_workspace("soma", 0.6, 0.6))

        # Process three frames with the control unblocked so the shadow has a baseline.
        for _ in range(3):
            await vision.process_frame(None)
        await vision._pc_queue.drain()
        initial_pc = await bus.read("positive_control.out", last_id="0")

        blocker = threading.Event()
        original_after_report = vision._positive_control.after_report

        def _blocked_after_report(*args, **kwargs):  # noqa: ARG001
            blocker.wait()
            return original_after_report(*args, **kwargs)

        vision._positive_control.after_report = _blocked_after_report

        await vision.process_frame(None)

        reports = await _reports(bus, "topos.out")
        assert len(reports) == 4
        pc_while_blocked = await bus.read("positive_control.out", last_id="0")
        assert len(pc_while_blocked) == len(initial_pc)

        blocker.set()
        await vision._pc_queue.drain()

        final_pc = await bus.read("positive_control.out", last_id="0")
        assert len(final_pc) == len(initial_pc) + 1
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_full_queue_fails_the_control_once() -> None:
    """A full queue fails the control once and only one terminal record is published."""
    bus = _bus()
    try:
        vision = vision_module.Vision(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=_control({"topos": 4}),
        )
        vision._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )
        await vision.on_workspace(_workspace("soma", 0.6, 0.6))

        import threading

        hold = threading.Event()
        control = vision._positive_control
        original_after_report = control.after_report

        def _held_then_raises(*args, **kwargs):
            # The in-flight control step blocks, then raises after the control
            # has already failed for a full queue.
            hold.wait()
            raise RuntimeError("released")

        control.after_report = _held_then_raises
        vision._pc_queue = ControlQueue(max_pending=1)

        # Report 1: its step runs and blocks. Report 2: queued. Report 3: the
        # queue is full, so the control fails and publishes its failure record.
        for _ in range(3):
            await vision.process_frame(None)
            await asyncio.sleep(0.05)
        assert vision._positive_control is None

        hold.set()
        await asyncio.wait_for(vision._pc_queue.drain(), timeout=5)
        await vision.finish_positive_control()
        control.after_report = original_after_report

        events = await bus.read("positive_control.out", last_id="0")
        payloads = _payloads(events)
        assert sum(1 for p in payloads if p["failed"]) == 1
        assert sum(1 for p in payloads if p["final"]) == 1
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_shutdown_drain_has_a_budget() -> None:
    """finish_positive_control times out a stuck queue and publishes one terminal record."""
    bus = _bus()
    try:
        import dataclasses
        settings = dataclasses.replace(
            _control({"topos": 4}),
            shutdown_drain_s=0.2,
        )
        vision = vision_module.Vision(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=settings,
        )
        vision._forward_model = LatentForwardModel(
            latent_dim=4,
            units=8,
            context_dim=CONTEXT_DIM,
            seed=4,
        )
        await vision.on_workspace(_workspace("soma", 0.6, 0.6))

        for _ in range(3):
            await vision.process_frame(None)

        never = asyncio.Event()

        async def _hung_job():
            await never.wait()

        assert vision._pc_queue.submit(_hung_job) is True

        await asyncio.wait_for(vision.finish_positive_control(), timeout=5)

        events = await bus.read("positive_control.out", last_id="0")
        payloads = _payloads(events)
        assert sum(1 for p in payloads if p["failed"] and p["final"]) == 1
        assert vision._positive_control is None
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_fail_positive_control_publishes_once() -> None:
    """Calling _fail_positive_control twice publishes a single failure record."""
    bus = _bus()
    try:
        control = _control({"topos": 4})
        vision = vision_module.Vision(
            bus,
            encoder=Varying(),
            forward_prediction=True,
            entity_clock=_FixedClock(),
            positive_control=control,
        )
        pc = vision._positive_control
        assert pc is not None
        await vision._fail_positive_control(pc, "x")
        await vision._fail_positive_control(pc, "x")

        events = await bus.read("positive_control.out", last_id="0")
        assert len(_payloads(events)) == 1
        assert vision._positive_control is None
    finally:
        await bus.close()


def test_from_config_shutdown_drain_s() -> None:
    """from_config accepts shutdown_drain_s in every mode and rejects bad values."""
    settings = PositiveControlSettings.from_config(
        {"enabled": True, "mode": "estimate_pc", "shutdown_drain_s": 2.5},
    )
    assert settings.shutdown_drain_s == 2.5

    with pytest.raises(ValueError):
        PositiveControlSettings.from_config({"enabled": False, "shutdown_drain_s": 0})

    with pytest.raises(ValueError):
        PositiveControlSettings.from_config({"enabled": False, "shutdown_drain_s": "x"})
