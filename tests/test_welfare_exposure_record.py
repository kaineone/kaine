# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The cycle's welfare exposure record (welfare-exposure-report).

Every boot deletes a stale state/welfare/exposure.json before the gates; a
research-mode shutdown writes one bound to its run (run_id, boot_started_at),
with indicator figures from the welfare monitor (never restarted) and shares
from the producer's tally with its coverage, as plain JSON, atomically, mode
0600, holding numbers, booleans, the run id, timestamps and table labels only.
"""
from __future__ import annotations

import asyncio
import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import kaine.cycle.__main__ as cycle_main
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event, validate_event
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import WelfareProtectiveMonitor, WelfareResponseConfig
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.evaluation.config import EvaluationConfig
from kaine.evaluation.observers.welfare_observer import WelfareObserver
from kaine.lifecycle.welfare_indicators import INDICATOR_NAMES, STAGE3_REASONS, IndicatorParams
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
from kaine.storage import resolve

T0 = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")


def _exposure_path() -> Path:
    return resolve(cycle_main.EXPOSURE_PATH)


def _stale_record() -> None:
    path = _exposure_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "run_id": "an-earlier-boot"}))


# --- removal at boot --------------------------------------------------------------


def _main_with(monkeypatch, config: dict[str, Any], env: dict[str, str]) -> int:
    for var in ("KAINE_CYCLE_UNATTENDED", "KAINE_CYCLE_OPERATOR_PRESENT", "KAINE_RESEARCH_MODE"):
        monkeypatch.delenv(var, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(cycle_main, "_load_kaine_config", lambda: config)

    async def no_boot(**kwargs):
        raise AssertionError("the boot must not start")

    monkeypatch.setattr(cycle_main, "_boot_and_run", no_boot)
    return cycle_main.main([])


def test_a_research_boot_refused_by_its_gate_leaves_no_record(monkeypatch):
    _stale_record()
    rc = _main_with(monkeypatch, {"supervisor": {"enabled": False}}, {"KAINE_RESEARCH_MODE": "1"})
    assert rc == 5
    assert not _exposure_path().exists()


def test_an_operator_boot_refused_leaves_no_record(monkeypatch):
    _stale_record()
    rc = _main_with(monkeypatch, {}, {})
    assert rc == 2
    assert not _exposure_path().exists()


def test_the_removal_runs_before_the_gates():
    import ast
    import inspect

    source = inspect.getsource(cycle_main.main)
    tree = ast.parse(source)
    calls = [
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    order = [c for c in calls if c in ("_remove_stale_exposure_record", "resolve_supervision_mode")]
    assert order[:2] == ["_remove_stale_exposure_record", "resolve_supervision_mode"]


# --- the record --------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


class _Sleep(BaseModule):
    name = "sleep"
    developmental_rest_s = 1410.0

    async def initialize(self):
        pass

    def serialize(self):
        return {}

    def welfare_rest_ready(self):
        return True


def _affect_payload(bored: bool) -> dict:
    return {
        "state": {"valence": 0.0, "arousal": 0.3},
        "drive_above": {"curiosity": False, "boredom": bored, "social_drive": False, "restlessness": False},
        "drive_ends": {
            "boredom": {"own": 0, "other": 0},
            "social_drive": {"own": 0, "other": 0},
            "restlessness": {"own": 0, "other": 0},
        },
    }


async def _boot_with_one_rest(bus: AsyncBus) -> tuple[WelfareProtectiveMonitor, WelfareObserver]:
    """A run whose boredom indicator crosses once: one rest requested, no freeze."""
    u = {"v": 0.0}
    w = {"v": T0}
    registry = ModuleRegistry()
    registry.register(_Sleep(bus))
    monitor = WelfareProtectiveMonitor(
        registry=registry,
        fork_manager=None,
        config=WelfareResponseConfig(enabled=True, warmup_s=0.0, warmup_ceiling_s=0.0),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=lambda: u["v"],
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=lambda: u["v"]
        ),
        indicator_params=IndicatorParams(),
        wall_time=lambda: w["v"],
    )

    class _Sink:
        async def write(self, row):
            pass

    observer = WelfareObserver(
        bus,
        _Sink(),
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=lambda: u["v"]
        ),
    )
    stop = asyncio.Event()
    await monitor._poll_once(stop)
    for step in range(320):
        ts = datetime.fromtimestamp(w["v"], timezone.utc)
        event = validate_event(
            source="affect", type="affect.state", payload=_affect_payload(True), salience=0.1, timestamp=ts
        )
        await bus.publish(event)
        await observer._handle_affect("x", event)
        u["v"] += 2.0
        w["v"] += 2.0
        if step % 15 == 14:
            await monitor._poll_once(stop)
            if monitor._ind_stage == "resting":
                break
    # The rest happens and completes; no second crossing follows.
    ts = datetime.fromtimestamp(w["v"], timezone.utc)
    request = monitor._ind_request.request_id
    for type_, payload in (
        ("sleep.sleep.started", {"trigger": "welfare_rest"}),
        ("sleep.rest_request", {"accepted": True, "reason": "accepted", "origin": "welfare", "proposal_id": request}),
        ("sleep.sleep.completed", {"trigger": "welfare_rest"}),
    ):
        event = validate_event(source="sleep", type=type_, payload=payload, salience=0.1, timestamp=ts)
        await bus.publish(event)
        await observer._handle_sleep("x", event)
    await monitor._poll_once(stop)
    for _ in range(30):
        ts = datetime.fromtimestamp(w["v"], timezone.utc)
        event = validate_event(
            source="affect", type="affect.state", payload=_affect_payload(False), salience=0.1, timestamp=ts
        )
        await bus.publish(event)
        await observer._handle_affect("x", event)
        u["v"] += 2.0
        w["v"] += 2.0
    await monitor._poll_once(stop)
    assert monitor._ind_stage == "fresh"
    return monitor, observer


def _eval_cfg(tmp_path: Path):
    return EvaluationConfig.from_mapping(
        {"enabled": False, "paths": {"evaluation_logs": str(tmp_path), "retention_days": 7}}
    )


def _content_free(record: dict[str, Any], run_id: str) -> None:
    labels = set(INDICATOR_NAMES) | set(STAGE3_REASONS) | {"boredom", "social_drive", "restlessness"}
    timestamps = {"boot_started_at", "written_at"}

    def check(key: str, value: Any) -> None:
        if value is None or isinstance(value, (bool, int, float)):
            return
        if isinstance(value, str):
            assert key in timestamps or (key == "run_id" and value == run_id), (key, value)
            if key in timestamps:
                datetime.fromisoformat(value)
            return
        assert isinstance(value, dict), (key, value)
        for k, v in value.items():
            if isinstance(v, dict) and k not in ("monitor", "shares", "indicators", "deficits", "responses"):
                assert k in labels, k
            check(k, v)

    for key, value in record.items():
        check(key, value)


@pytest.mark.asyncio
async def test_a_boot_with_one_rest_writes_its_bound_record(bus, tmp_path):
    monitor, observer = await _boot_with_one_rest(bus)
    run_ctx = SimpleNamespace(run_id="run-0123abcd", started_at="2026-10-31T12:00:00+00:00")
    cycle_main._write_exposure_record(
        run_ctx=run_ctx,
        welfare_monitor=monitor,
        welfare_producer=(observer, None),
        welfare_supervision={"restarts": 0},
        eval_cfg=_eval_cfg(tmp_path),
    )
    path = _exposure_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    record = json.loads(path.read_text())  # plain JSON
    assert record["schema"] == 1
    assert record["run_id"] == "run-0123abcd"
    assert record["boot_started_at"] == "2026-10-31T12:00:00+00:00"
    boredom = record["monitor"]["indicators"]["boredom_deprived"]
    assert boredom["crossings"] == 1
    assert boredom["rests_requested"] == 1
    assert boredom["freezes_placed"] == 0
    assert boredom["max_value"] == pytest.approx(1.0)
    assert record["monitor"]["rests_requested"] == 1
    assert record["monitor"]["freezes_placed"] == 0
    assert record["producer_restarts"] == 0
    assert record["covered_awake_seconds"] == pytest.approx(record["shares"]["awake_seconds"])
    assert record["shares"]["deficits"]["boredom"]["deprivation_share"] > 0.5
    assert record["affect_summary_interval_s"] == 300.0
    _content_free(record, "run-0123abcd")


@pytest.mark.asyncio
async def test_a_restarted_producer_shows_in_the_coverage(bus, tmp_path):
    monitor, _observer = await _boot_with_one_rest(bus)

    class _Sink:
        async def write(self, row):
            pass

    # The rebuilt producer saw only the end of the run.
    late = WelfareObserver(bus, _Sink())
    for t in range(20):
        ts = datetime.fromtimestamp(T0 + 5000 + t, timezone.utc)
        await late._handle_affect(
            "x",
            Event(source="affect", type="affect.state", payload=_affect_payload(False), salience=0.1, timestamp=ts),
        )
    record = cycle_main._exposure_record(
        run_ctx=SimpleNamespace(run_id="r1", started_at="2026-10-31T12:00:00+00:00"),
        welfare_monitor=monitor,
        welfare_producer=(late, None),
        welfare_supervision={"restarts": 1},
        eval_cfg=_eval_cfg(tmp_path),
    )
    assert record["producer_restarts"] == 1
    assert record["covered_awake_seconds"] < record["monitor"]["awake_seconds"]
    # The indicator figures still cover the whole run.
    assert record["monitor"]["indicators"]["boredom_deprived"]["crossings"] == 1


def test_a_failed_write_is_logged_and_does_not_raise(monkeypatch, caplog):
    def broken(path, payload):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cycle_main, "write_json_atomic", broken)
    with caplog.at_level("ERROR"):
        cycle_main._write_exposure_record(
            run_ctx=SimpleNamespace(run_id="r1", started_at="2026-10-31T12:00:00+00:00"),
            welfare_monitor=None,
            welfare_producer=None,
            welfare_supervision=None,
            eval_cfg=None,
        )
    assert "could not write the welfare exposure record" in caplog.text
    assert not _exposure_path().exists()


def test_without_a_monitor_the_record_says_so(tmp_path):
    record = cycle_main._exposure_record(
        run_ctx=SimpleNamespace(run_id="r1", started_at="2026-10-31T12:00:00+00:00"),
        welfare_monitor=None,
        welfare_producer=None,
        welfare_supervision=None,
        eval_cfg=None,
    )
    assert record["monitor"] is None and record["shares"] is None
    assert record["producer_restarts"] is None and record["covered_awake_seconds"] is None


@pytest.mark.asyncio
async def test_only_a_research_shutdown_writes_the_record(tmp_path, monkeypatch):
    written: list[str] = []
    monkeypatch.setattr(cycle_main, "_write_exposure_record", lambda **kw: written.append(kw["run_ctx"].run_id))

    class _Bus:
        async def close(self):
            pass

    class _Cycle:
        is_paused = False

        async def shutdown(self):
            pass

    for mode in ("research", "operator", "unattended"):
        ctx = cycle_main.BootContext(
            supervision_mode=mode,
            kaine_config={},
            registry=ModuleRegistry(),
            bus=_Bus(),
            cycle=_Cycle(),
            run_ctx=SimpleNamespace(run_id=f"run-{mode}", started_at="t"),
            supervisor=SimpleNamespace(escalated=False),
        )

        async def _never():
            await asyncio.Event().wait()

        ctx.freeze_task = asyncio.create_task(asyncio.sleep(0))
        ctx.cycle_task = asyncio.create_task(_never())
        await cycle_main._shutdown(ctx)
    assert written == ["run-research"]


# --- coverage under time dilation ----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("scale", [1.0, 2.0])
async def test_a_clean_dilated_boot_round_trips_without_a_coverage_hold(bus, tmp_path, scale):
    """The real monitor (spans on the awake entity clock), the real tally (wall
    seconds), the real writer and the runner's real reader: a clean boot at
    time scale 2 is not held for incomplete coverage."""
    from kaine.research.ignition_study.runner import EXPOSURE_FILE, read_step_exposure

    u = {"v": 0.0}
    w = {"v": T0}
    registry = ModuleRegistry()
    registry.register(_Sleep(bus))
    monitor = WelfareProtectiveMonitor(
        registry=registry,
        fork_manager=None,
        config=WelfareResponseConfig(enabled=True, warmup_s=0.0, warmup_ceiling_s=0.0),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=lambda: u["v"],
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=lambda: u["v"]
        ),
        indicator_params=IndicatorParams(),
        awake_clock=lambda: u["v"] * scale,
        entity_scale=lambda: scale,
        wall_time=lambda: w["v"],
    )

    class _Sink:
        async def write(self, row):
            pass

    observer = WelfareObserver(
        bus,
        _Sink(),
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=lambda: u["v"]
        ),
    )
    stop = asyncio.Event()
    await monitor._poll_once(stop)
    # One affect.state per entity second for 900 wall seconds.
    period = 1.0 / scale
    for step in range(int(900 * scale)):
        ts = datetime.fromtimestamp(w["v"], timezone.utc)
        event = validate_event(
            source="affect", type="affect.state", payload=_affect_payload(False), salience=0.1, timestamp=ts
        )
        await bus.publish(event)
        await observer._handle_affect("x", event)
        u["v"] += period
        w["v"] += period
        if step % 20 == 19:
            await monitor._poll_once(stop)
    await monitor._poll_once(stop)
    summary = monitor.exposure_summary()
    assert summary["awake_seconds"] == pytest.approx(900.0 * scale, abs=3.0)
    assert summary["awake_wall_seconds"] == pytest.approx(900.0, abs=3.0)

    started_at = "2026-10-31T12:00:00+00:00"
    cycle_main._write_exposure_record(
        run_ctx=SimpleNamespace(run_id="run-dilated", started_at=started_at),
        welfare_monitor=monitor,
        welfare_producer=(observer, None),
        welfare_supervision={"restarts": 0},
        eval_cfg=_eval_cfg(tmp_path),
    )
    path = _exposure_path()
    line_dir = path.parents[2]
    assert line_dir / EXPOSURE_FILE == path
    exposure, reasons = read_step_exposure(line_dir, run_id="run-dilated", since_iso=started_at)
    assert exposure is not None
    assert reasons == []


@pytest.mark.asyncio
async def test_an_unreadable_time_scale_leaves_the_wall_count_unknown(bus, tmp_path):
    def broken_scale() -> float:
        raise RuntimeError("scale unreadable")

    u = {"v": 0.0}
    w = {"v": T0}
    registry = ModuleRegistry()
    registry.register(_Sleep(bus))
    monitor = WelfareProtectiveMonitor(
        registry=registry,
        fork_manager=None,
        config=WelfareResponseConfig(enabled=True, warmup_s=0.0, warmup_ceiling_s=0.0),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=lambda: u["v"],
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=lambda: u["v"]
        ),
        indicator_params=IndicatorParams(),
        awake_clock=lambda: u["v"] * 2.0,
        entity_scale=broken_scale,
        wall_time=lambda: w["v"],
    )
    stop = asyncio.Event()
    await monitor._poll_once(stop)
    for step in range(40):
        ts = datetime.fromtimestamp(w["v"], timezone.utc)
        await bus.publish(validate_event(
            source="affect", type="affect.state", payload=_affect_payload(False), salience=0.1, timestamp=ts
        ))
        u["v"] += 0.5
        w["v"] += 0.5
        if step % 20 == 19:
            await monitor._poll_once(stop)
    summary = monitor.exposure_summary()
    assert summary["awake_seconds"] > 0
    assert summary["awake_wall_seconds"] is None
