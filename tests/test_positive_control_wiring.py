# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Wiring tests for the positive-control shadow of the information-gain measure."""

from __future__ import annotations

import math
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.boot import make_soma
from kaine.boot.registry import construct_module
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.positive_control import (
    RESULT_FIELDS,
    PositiveControlSettings,
)
from kaine.modules.registry import ModuleRegistry
from kaine.modules.soma.detector import AlertResult
from kaine.modules.soma.module import Soma
from kaine.modules.topos.forward import LatentForwardModel
from kaine.modules.topos.module import Topos


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


def test_shipped_config_leaves_the_control_off():
    path = Path(__file__).resolve().parents[1] / "config" / "kaine.toml"
    with path.open("rb") as fh:
        config = tomllib.load(fh)
    pc = config["positive_control"]
    assert pc["enabled"] is False
    assert "min_effect" not in pc
    assert "snr" not in pc


def test_soma_factory_builds_the_control_only_when_enabled():
    bus = _bus()
    assert make_soma(bus, {})._positive_control is None
    controlled = make_soma(
        bus,
        {"positive_control": {"enabled": True, "snr": 10.0, "min_effect": 0.01}},
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
            "positive_control": {"enabled": True, "snr": 5.0},
        },
        registry=ModuleRegistry(),
    )
    assert isinstance(module, BaseModule)
    assert module._positive_control is not None


@pytest.mark.asyncio
async def test_topos_control_publishes_and_leaves_the_live_report_untouched() -> None:
    uncontrolled_bus = _bus()
    controlled_bus = _bus()

    uncontrolled = Topos(
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

    controlled = Topos(
        controlled_bus,
        encoder=Varying(),
        forward_prediction=True,
        entity_clock=_FixedClock(),
        positive_control=PositiveControlSettings(enabled=True, snr=10.0, min_effect=0.01),
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


@pytest.mark.asyncio
async def test_soma_control_publishes_results(bus: AsyncBus) -> None:
    soma = Soma(
        bus,
        reader=FakeMetricsReader({"cpu_percent": 10.0, "ram_percent": 20.0}),
        detector=NeverAlertDetector(),
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
    topos = Topos(
        bus,
        encoder=Varying(),
        forward_prediction=True,
        positive_control=PositiveControlSettings(enabled=True, snr=10.0, min_effect=0.01),
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
