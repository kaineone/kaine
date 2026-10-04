# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The welfare net's gray-zone producer runs independently of [evaluation]."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.cycle import control_state
from kaine.cycle.__main__ import _start_welfare_producer
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import (
    PreservationConfig,
    WelfareProtectiveMonitor,
    WelfareResponseConfig,
)
from kaine.evaluation.config import EvaluationConfig
from kaine.evaluation.observers.welfare_observer import (
    WelfareObserver,
    build_welfare_producer,
)
from kaine.evaluation.registry import SidecarRegistry
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.modules.eidolon import Eidolon, SelfModel
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _run_context():
    set_run_context(
        RunContext(
            run_id="welfarenetrun0123456",
            seed=7,
            started_at=datetime.now(timezone.utc).isoformat(),
            git_sha=None,
        )
    )
    yield
    set_run_context(None)


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    yield


# ---------------------------------------------------------------------------
# Test helpers (copied from tests/test_preservation_monitors.py)
# ---------------------------------------------------------------------------


async def _entity(bus: AsyncBus, tmp_path: Path, *, name="Aria"):
    reg = ModuleRegistry()
    eid = Eidolon(bus, persistence_path=tmp_path / "sm.json", save_interval_s=60)
    await eid.initialize()
    eid._model = SelfModel(name=name, values=["honesty"])
    reg.register(eid)
    return reg, eid


class _StubFM:
    """ForkManager double recording preserve_live calls without touching disk."""

    def __init__(self):
        self.calls = []

    async def preserve_live(
        self, registry, *, reason, label, out_root, entity_name, require_encryption=False
    ):
        self.calls.append(
            {"reason": reason, "label": label, "out_root": out_root, "entity_name": entity_name}
        )


def _welfare_monitor(bus, registry, fm, cfg, *, on_end=None, clock=None, warmup_s=0.0):
    cfg.warmup_s = warmup_s
    mon = WelfareProtectiveMonitor(
        registry=registry,
        fork_manager=fm,
        config=cfg,
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        on_end=on_end,
    )
    if clock is not None:
        mon._clock = clock
    return mon


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_welfare_producer_matches_registry_shape(bus, tmp_path):
    eval_cfg = EvaluationConfig.from_mapping(
        {
            "enabled": False,
            "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7},
            "welfare": {
                "interoceptive_distress_threshold": 0.8,
                "interoceptive_distress_duration_s": 30.0,
            },
        },
        lingua_model_id=None,
    )
    observer, sink = build_welfare_producer(bus, eval_cfg)
    assert isinstance(observer, WelfareObserver)
    assert isinstance(sink, AsyncJsonlSink)
    assert sink.name == "welfare"
    assert sink.directory.name == "welfare"


@pytest.mark.asyncio
async def test_registry_does_not_build_a_second_welfare_observer(bus, tmp_path):
    eval_cfg = EvaluationConfig.from_mapping(
        {
            "enabled": True,
            "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7},
            "observers": {
                "welfare": True,
                "coherence": False,
                "replay": False,
                "empatheia": False,
                "voice_alignment_divergence": False,
                "fatigue": False,
                "prediction_error": False,
                "nous_policy": False,
            },
        },
        lingua_model_id=None,
    )
    external, _external_sink = build_welfare_producer(bus, eval_cfg)
    registry = SidecarRegistry(bus=bus, config=eval_cfg, welfare_observer=external)
    registry.build()
    assert registry.welfare_observer is external
    assert external not in registry.observers
    assert all(not isinstance(o, WelfareObserver) for o in registry.observers)

    registry2 = SidecarRegistry(bus=bus, config=eval_cfg)
    registry2.build()
    assert registry2.welfare_observer is not None
    assert registry2.welfare_observer is not external
    welfare_observers = [o for o in registry2.observers if isinstance(o, WelfareObserver)]
    assert len(welfare_observers) == 1


@pytest.mark.asyncio
async def test_welfare_producer_starts_only_with_welfare_response(bus, tmp_path):
    eval_cfg = EvaluationConfig.from_mapping(
        {"enabled": False, "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7}},
        lingua_model_id=None,
    )
    disabled_cfg = PreservationConfig.from_section({"welfare_response": {"enabled": False}})
    assert await _start_welfare_producer(bus, eval_cfg, disabled_cfg) is None

    enabled_cfg = PreservationConfig.from_section({"welfare_response": {"enabled": True}})
    producer = await _start_welfare_producer(bus, eval_cfg, enabled_cfg)
    assert producer is not None
    observer, sink = producer
    assert isinstance(observer, WelfareObserver)
    assert isinstance(sink, AsyncJsonlSink)
    assert observer._task is not None and not observer._task.done()
    await observer.stop()
    await sink.stop()


@pytest.mark.asyncio
async def test_welfare_producer_start_failure_refuses_to_run(bus, tmp_path, monkeypatch):
    eval_cfg = EvaluationConfig.from_mapping(
        {"enabled": False, "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7}},
        lingua_model_id=None,
    )
    preservation_cfg = PreservationConfig.from_section(
        {"welfare_response": {"enabled": True}}
    )

    async def failing_start(self):
        raise OSError("disk")

    monkeypatch.setattr(AsyncJsonlSink, "start", failing_start)

    stops = []

    orig_observer_stop = WelfareObserver.stop
    async def recording_observer_stop(self):
        stops.append("WelfareObserver")
        return await orig_observer_stop(self)

    orig_sink_stop = AsyncJsonlSink.stop
    async def recording_sink_stop(self):
        stops.append("AsyncJsonlSink")
        return await orig_sink_stop(self)

    monkeypatch.setattr(WelfareObserver, "stop", recording_observer_stop)
    monkeypatch.setattr(AsyncJsonlSink, "stop", recording_sink_stop)

    with pytest.raises(RuntimeError, match="gray-zone producer could not start"):
        await _start_welfare_producer(bus, eval_cfg, preservation_cfg)

    assert "WelfareObserver" in stops
    assert "AsyncJsonlSink" in stops


@pytest.mark.asyncio
async def test_gray_zone_reaches_the_monitor_with_evaluation_off(bus, tmp_path):
    eval_cfg = EvaluationConfig.from_mapping(
        {
            "enabled": False,
            "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7},
            "welfare": {
                "interoceptive_distress_threshold": 0.8,
                "interoceptive_distress_duration_s": 30.0,
            },
        },
        lingua_model_id=None,
    )
    preservation_cfg = PreservationConfig.from_section(
        {"welfare_response": {"enabled": True}}
    )
    observer, sink = await _start_welfare_producer(bus, eval_cfg, preservation_cfg)

    # Lower the replay threshold so small bursts fire quickly in the test.
    observer._consolidation_window_s = 5.0
    observer._replay_rate_threshold = 3

    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    response_cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=9999.0,
        repeat_window_s=300.0,
        repeat_threshold=3,
        out_root=str(tmp_path / "backups"),
    )
    mon = _welfare_monitor(bus, reg, fm, response_cfg)
    stop = asyncio.Event()

    # Three bursts of replay events, each enough to fire one replay_overload.
    for burst in range(3):
        for i in range(5):
            await bus.publish(
                validate_event(
                    source="mnemos",
                    type="mnemos.replay",
                    payload={"memory_id": f"mem-{burst}-{i}", "text": "x"},
                    salience=0.1,
                    timestamp=datetime.now(timezone.utc),
                )
            )
        await asyncio.sleep(0.15)

    deadline = asyncio.get_running_loop().time() + 5.0
    gray_zones = []
    while len(gray_zones) < 3:
        if asyncio.get_running_loop().time() > deadline:
            break
        entries, _ = await bus.read_entries(
            "welfare.out", last_id="0", count=256, block_ms=100
        )
        gray_zones = [
            event for _eid, event in entries if event.type == "welfare.gray_zone"
        ]
        if len(gray_zones) < 3:
            await asyncio.sleep(0.05)

    assert len(gray_zones) >= 3
    await mon._poll_once(stop)
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] == "welfare"

    await observer.stop()
    await sink.stop()
    await eid.shutdown()
