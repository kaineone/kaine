# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The welfare net's gray-zone producer runs independently of [evaluation]."""

from __future__ import annotations

import asyncio
import sys
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
async def test_supervisor_ignores_a_live_producer(bus, tmp_path):
    from kaine.cycle.__main__ import _supervise_welfare_producer

    eval_cfg = EvaluationConfig.from_mapping(
        {"enabled": False, "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7}},
        lingua_model_id=None,
    )
    preservation_cfg = PreservationConfig.from_section(
        {"welfare_response": {"enabled": True}}
    )
    producer = await _start_welfare_producer(bus, eval_cfg, preservation_cfg)
    observer, sink = producer
    original_task = observer._task

    state = {}
    await _supervise_welfare_producer(producer, state, now=100.0)
    assert "restarts" not in state
    assert observer._task is original_task

    await observer.stop()
    await sink.stop()


@pytest.mark.asyncio
async def test_supervisor_restarts_a_dead_producer(bus, tmp_path):
    from kaine.cycle.__main__ import _supervise_welfare_producer

    eval_cfg = EvaluationConfig.from_mapping(
        {"enabled": False, "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7}},
        lingua_model_id=None,
    )
    preservation_cfg = PreservationConfig.from_section(
        {"welfare_response": {"enabled": True}}
    )
    producer = await _start_welfare_producer(bus, eval_cfg, preservation_cfg)
    observer, sink = producer
    original_task = observer._task

    original_task.cancel()
    try:
        await original_task
    except asyncio.CancelledError:
        pass  # expected: the test cancelled this task itself

    state = {}
    await _supervise_welfare_producer(producer, state, now=100.0)
    assert observer._task is not None
    assert observer._task is not original_task
    assert not observer._task.done()
    assert state["restarts"] == 1
    assert state["next_restart_at"] == 105.0

    observer._task.cancel()
    try:
        await observer._task
    except asyncio.CancelledError:
        pass  # expected: the test cancelled this task itself

    await _supervise_welfare_producer(producer, state, now=101.0)
    assert state["restarts"] == 1

    await _supervise_welfare_producer(producer, state, now=106.0)
    assert state["restarts"] == 2
    assert state["next_restart_at"] == 116.0

    await observer.stop()
    await sink.stop()


@pytest.mark.asyncio
async def test_restarted_producer_does_not_replay_backlog(bus, tmp_path):
    from kaine.cycle.__main__ import _supervise_welfare_producer

    eval_cfg = EvaluationConfig.from_mapping(
        {"enabled": False, "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7}},
        lingua_model_id=None,
    )
    preservation_cfg = PreservationConfig.from_section(
        {"welfare_response": {"enabled": True}}
    )
    producer = await _start_welfare_producer(bus, eval_cfg, preservation_cfg)
    observer, sink = producer

    # Lower the replay threshold so the single burst fires quickly in the test.
    observer._consolidation_window_s = 5.0
    observer._replay_rate_threshold = 3

    # Publish one burst of replay events.
    for i in range(5):
        await bus.publish(
            validate_event(
                source="mnemos",
                type="mnemos.replay",
                payload={"memory_id": f"mem-0-{i}", "text": "x"},
                salience=0.1,
                timestamp=datetime.now(timezone.utc),
            )
        )

    # Wait until the welfare observer has counted exactly one replay overload.
    deadline = asyncio.get_running_loop().time() + 5.0
    while observer.replay_overload_count < 1:
        if asyncio.get_running_loop().time() > deadline:
            break
        await asyncio.sleep(0.05)
    assert observer.replay_overload_count == 1

    before = observer.replay_overload_count
    before_cursors = observer._cursors.copy()

    # Crash the observer task, then restart it via the supervisor.
    observer._task.cancel()
    try:
        await observer._task
    except asyncio.CancelledError:
        pass  # expected: the test cancelled this task itself

    await _supervise_welfare_producer(producer, {}, now=0.0)

    # Longer than the 0.5 s poll interval, so a restart would have time to replay.
    await asyncio.sleep(0.6)

    assert observer.replay_overload_count == before
    for stream, old_cursor in before_cursors.items():
        current_cursor = observer._cursors.get(stream, "0")
        assert current_cursor >= old_cursor, (
            f"cursor for {stream} regressed from {old_cursor!r} to {current_cursor!r}"
        )
        assert current_cursor != "0" or old_cursor == "0", (
            f"cursor for {stream} was reset to '0' after restart"
        )

    await observer.stop()
    await sink.stop()


@pytest.mark.asyncio
async def test_producer_construction_failure_refuses(bus, tmp_path, monkeypatch):
    eval_cfg = EvaluationConfig.from_mapping(
        {"enabled": False, "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7}},
        lingua_model_id=None,
    )
    preservation_cfg = PreservationConfig.from_section(
        {"welfare_response": {"enabled": True}}
    )

    def bad_build(*args, **kwargs):
        raise OSError("bad path")

    monkeypatch.setattr(
        "kaine.evaluation.observers.welfare_observer.build_welfare_producer", bad_build
    )

    with pytest.raises(RuntimeError, match="gray-zone producer could not start"):
        await _start_welfare_producer(bus, eval_cfg, preservation_cfg)


def test_boot_wiring_order():
    import ast
    import inspect

    entry = sys.modules[_start_welfare_producer.__module__]
    source_path = Path(inspect.getsourcefile(entry))
    source = source_path.read_text()
    tree = ast.parse(source)

    boot = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_boot_and_run":
            boot = node
            break
    assert boot is not None, "_boot_and_run not found in source"

    def _collect_calls(node):
        calls = []
        for child in ast.iter_child_nodes(node):
            calls.extend(_collect_calls(child))
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            calls.append((name, node.lineno))
        return calls

    all_calls = _collect_calls(boot)

    def _first(name):
        for n, lineno in all_calls:
            if n == name:
                return lineno
        raise AssertionError(f"{name} not found in _boot_and_run")

    audit_lineno = _first("audit")
    producer_start_lineno = _first("_start_welfare_producer")
    build_registry_lineno = _first("build_registry")
    sidecar_registry_lineno = _first("SidecarRegistry")

    assert audit_lineno < producer_start_lineno
    assert producer_start_lineno < build_registry_lineno
    assert build_registry_lineno < sidecar_registry_lineno

    sidecar_kwarg_found = False
    for node in ast.walk(boot):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "SidecarRegistry"
        ):
            if any(kw.arg == "welfare_observer" for kw in node.keywords):
                sidecar_kwarg_found = True
                break
    assert sidecar_kwarg_found

    stop_calls = sum(1 for n, _ in all_calls if n == "_stop_welfare_producer")
    assert stop_calls >= 3


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


@pytest.mark.asyncio
async def test_cancel_during_emit_leaves_detector_state_consistent(bus, tmp_path):
    """A cancellation while a gray-zone event is being emitted must not leave
    the replay window un-cleared; otherwise a restarted observer re-fires the
    same burst on the next replay event."""
    eval_cfg = EvaluationConfig.from_mapping(
        {"enabled": False, "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7}},
        lingua_model_id=None,
    )
    observer, _sink = build_welfare_producer(bus, eval_cfg)
    observer._consolidation_window_s = 60.0
    observer._replay_rate_threshold = 3

    blocked = asyncio.Event()

    async def _blocking_emit(record):
        blocked.set()
        await asyncio.Event().wait()  # never returns; the test cancels it

    observer._emit_gray_zone = _blocking_emit

    def _replay(i):
        return validate_event(
            source="mnemos",
            type="mnemos.replay",
            payload={"memory_id": f"m-{i}"},
            salience=0.1,
            timestamp=datetime.now(timezone.utc),
        )

    async def _feed():
        for i in range(4):
            await observer._handle_mnemos(f"{i}-0", _replay(i))

    task = asyncio.create_task(_feed())
    await asyncio.wait_for(blocked.wait(), timeout=2.0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass  # expected: the test cancelled this task itself

    assert observer.replay_overload_count == 1
    assert len(observer._replay_timestamps) == 0
