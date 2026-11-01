# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The welfare observer's affect_welfare record carries the live A.4 indicators.

The observer runs its own instance of the evaluator the welfare monitor runs,
so a person reviewing the run sees what the monitor saw. The dashboard readout
knows the new keys and bounds them.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event, validate_event
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import WelfareProtectiveMonitor, WelfareResponseConfig
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.evaluation.observers.welfare_observer import WelfareObserver
from kaine.experiment.welfare_counts import AFFECT_WELFARE_KEYS, affect_welfare_from_jsonl
from kaine.lifecycle.welfare_indicators import INDICATOR_NAMES, IndicatorParams
from kaine.modules.registry import ModuleRegistry

T0 = datetime(2026, 10, 31, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")


class _Mono:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class FakeSink:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def write(self, row: dict) -> None:
        self.rows.append(row)


class FakeBus:
    async def read_entries(self, stream, *, last_id, count, block_ms):
        return [], None

    async def latest(self, stream):
        return None

    async def publish(self, event):
        return "0-0"


def _payload(t: int) -> dict:
    return {
        "state": {"valence": -0.6 if t % 9 < 4 else 0.2, "arousal": 0.3},
        "drive_above": {
            "curiosity": False,
            "boredom": t % 5 < 3,
            "social_drive": t % 7 == 0,
            "restlessness": False,
        },
        "drive_ends": {
            "boredom": {"own": 0, "other": t // 200},
            "social_drive": {"own": 0, "other": 0},
            "restlessness": {"own": t // 400, "other": 0},
        },
    }


def _quiet_payload(t: int) -> dict:
    """A varied affect state that crosses no bar, so the monitor stays armed."""
    return {
        "state": {"valence": -0.6 if t % 9 < 3 else 0.2, "arousal": 0.3},
        "drive_above": {
            "curiosity": False,
            "boredom": t % 5 < 2,
            "social_drive": t % 7 == 0,
            "restlessness": t % 3 == 0,
        },
        "drive_ends": {
            "boredom": {"own": t // 300, "other": t // 300},
            "social_drive": {"own": 0, "other": 0},
            "restlessness": {"own": t // 500, "other": 0},
        },
    }


async def _observer_record(seconds: int, sleep_at: tuple[int, int] | None) -> dict:
    u = _Mono()
    sink = FakeSink()
    obs = WelfareObserver(
        FakeBus(),
        sink,
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=u
        ),
        indicator_params=IndicatorParams(),
    )
    for t in range(seconds):
        ts = T0 + timedelta(seconds=t)
        if sleep_at and t == sleep_at[0]:
            await obs._handle_sleep("s", Event(source="sleep", type="sleep.sleep.started", payload={}, salience=0.1, timestamp=ts))
        if sleep_at and t == sleep_at[1]:
            await obs._handle_sleep("s", Event(source="sleep", type="sleep.sleep.completed", payload={}, salience=0.1, timestamp=ts))
        await obs._handle_affect("a", Event(source="affect", type="affect.state", payload=_payload(t), salience=0.1, timestamp=ts))
        u.value += 1.0
    await obs._write_affect_summary()
    return sink.rows[-1]


def test_the_record_carries_every_indicator():
    record = asyncio.run(_observer_record(900, None))
    assert record["record"] == "affect_welfare"
    assert record["indicator_span_awake_seconds"] == pytest.approx(899.0)
    for name in INDICATOR_NAMES:
        assert f"indicator_{name}_value" in record
        assert f"indicator_{name}_bar" in record
        assert record[f"indicator_{name}_over"] in (0, 1)
    assert record["indicator_boredom_deprived_value"] == pytest.approx(0.6, abs=0.01)
    assert record["indicator_boredom_deprived_over"] == 1
    for key in AFFECT_WELFARE_KEYS:
        assert key in record


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_the_record_shows_the_monitors_numbers(bus):
    """The monitor and the observer read the same affect.state and sleep events."""
    u = _Mono()
    wall = _Mono(T0.timestamp())
    monitor = WelfareProtectiveMonitor(
        registry=ModuleRegistry(),
        fork_manager=None,
        config=WelfareResponseConfig(enabled=True, warmup_s=0.0, warmup_ceiling_s=0.0),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=u,
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=u
        ),
        indicator_params=IndicatorParams(),
        wall_time=wall,
    )
    stop = asyncio.Event()
    await monitor._poll_once(stop)
    observer = WelfareObserver(
        FakeBus(),
        FakeSink(),
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=u
        ),
        indicator_params=IndicatorParams(),
    )
    for t in range(1, 1201):
        ts = datetime.fromtimestamp(wall.value, timezone.utc)
        events = []
        if t == 400:
            events.append(("sleep", "sleep.sleep.started"))
        if t == 700:
            events.append(("sleep", "sleep.sleep.completed"))
        for source, type_ in events:
            event = validate_event(source=source, type=type_, payload={}, salience=0.1, timestamp=ts)
            await bus.publish(event)
            await observer._handle_sleep("x", event)
        event = validate_event(source="affect", type="affect.state", payload=_quiet_payload(t), salience=0.1, timestamp=ts)
        await bus.publish(event)
        await observer._handle_affect("x", event)
        wall.value += 1.0
        u.value += 1.0
        if t % 20 == 0:
            await monitor._poll_once(stop)
    # Nothing crossed: the monitor never acted, so neither instance saw a freeze.
    assert monitor._ind_stage == "armed" and not monitor._acted
    mon_eval = monitor._ind_eval.peek()
    obs_eval = observer._indicators.peek()
    assert mon_eval.span_awake_s == pytest.approx(900.0, abs=2.0)
    assert mon_eval.span_awake_s == pytest.approx(obs_eval.span_awake_s, abs=1.0)
    for name in INDICATOR_NAMES:
        m = mon_eval.reading(name).value
        o = obs_eval.reading(name).value
        assert m == pytest.approx(o, abs=0.005), name


def test_the_readout_knows_and_bounds_the_indicator_keys(tmp_path: Path):
    logs = tmp_path / "logs"
    welfare = logs / "welfare"
    welfare.mkdir(parents=True)
    record = {"ts": T0.isoformat(), "record": "affect_welfare"}
    for key in AFFECT_WELFARE_KEYS:
        record[key] = 0.5
    record["indicator_boredom_deprived_over"] = 1
    record["indicator_negative_valence_over"] = 0.5  # not a flag
    record["indicator_boredom_uncontrolled_value"] = 1.2  # outside [0, 1]
    record["indicator_span_awake_seconds"] = -3.0
    (welfare / "welfare-1.jsonl").write_text(json.dumps(record) + "\n")
    result = affect_welfare_from_jsonl(logs)
    assert result is not None
    assert result["indicator_boredom_deprived_value"] == 0.5
    assert result["indicator_boredom_deprived_over"] == 1
    assert result["indicator_negative_valence_over"] is None
    assert result["indicator_boredom_uncontrolled_value"] is None
    assert result["indicator_span_awake_seconds"] is None
