# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""A failed read never discards a crossing the same poll already found.

The real welfare monitor on fakeredis, sustained distress from t = 0 with a
30 s duration and 1 s polls: healthy, the protective response comes at
t = 31 s. When a read on the crossing poll hangs (a WelfareBusTimeout) or fails
a third time in a row (WelfareBusReadFailing), the poll still fails for the
liveness check, but only after the crossing it found has been answered: the
sustained-distress tracker fires once per episode, so a dropped crossing would
wait a whole new episode, or never be answered if the distress eased.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import (
    _WELFARE_BUS_TIMEOUT_S,
    WelfareBusReadFailing,
    WelfareBusTimeout,
    WelfareIndicatorConfig,
    WelfareProtectiveMonitor,
    WelfareResponseConfig,
)
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.lifecycle.preservation import PreservationResult
from kaine.modules.registry import ModuleRegistry

pytestmark = pytest.mark.asyncio

T0 = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(control_state, "OVERRIDE_AUDIT_PATH", tmp_path / "audit.jsonl")


class _Bus:
    """The real bus, with reads of ``stream`` misbehaving while ``bad`` is set."""

    def __init__(self, inner: AsyncBus, stream: str, mode: str) -> None:
        self.inner = inner
        self.stream = stream
        self.mode = mode
        self.bad = False
        self.hang_publish = False

    async def publish(self, event):
        if self.hang_publish:
            await asyncio.sleep(3600)
        return await self.inner.publish(event)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def read_entries(self, stream, **kw):
        if self.bad and stream == self.stream:
            if self.mode == "hang":
                await asyncio.sleep(3600)
            raise ConnectionError(f"{stream} unreadable")
        return await self.inner.read_entries(stream, **kw)


class _FM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def preserve_live(self, registry, **kw):
        self.calls.append(kw["reason"])
        return PreservationResult(
            ok=True, preservation_id="p", snapshot_id="s", reason="welfare",
            label="l", run_id="r", world_model_captured=False,
        )


async def _respond_time(
    stream: str, mode: str | None, *, hang_publish: bool = False
) -> tuple[float | None, list]:
    inner = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=pytest.importorskip("fakeredis.aioredis").FakeRedis(decode_responses=True),
    )
    bus = _Bus(inner, stream, mode or "none")
    bus.hang_publish = hang_publish
    u = {"v": 0.0}
    fm = _FM()
    monitor = WelfareProtectiveMonitor(
        registry=ModuleRegistry(),
        fork_manager=fm,
        config=WelfareResponseConfig(
            enabled=True, warmup_s=0.0, warmup_ceiling_s=0.0,
            indicators=WelfareIndicatorConfig(enabled=False),
        ),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=lambda: u["v"],
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=lambda: u["v"]
        ),
        bus_timeout_s=0.05,
    )
    stop = asyncio.Event()
    failed: list[tuple[float, str]] = []
    responded = None
    try:
        for _ in range(120):
            await inner.publish(validate_event(
                source="interoception", type="interoception.report",
                payload={"prediction_error": 0.95, "warmup_active": False}, salience=0.5,
                timestamp=datetime.fromtimestamp(T0 + u["v"], timezone.utc),
            ))
            u["v"] += 1.0
            # Misbehave on the polls around the 30 s crossing; "raise3" fails
            # the read three polls in a row, so the third fails the poll.
            bus.bad = (mode == "hang" and 30 <= u["v"] <= 31) or (mode == "raise3" and 29 <= u["v"] <= 31)
            try:
                # A poll always returns: every bus call in it is bounded.
                await asyncio.wait_for(monitor._poll_once(stop), timeout=10.0)
            except (WelfareBusTimeout, WelfareBusReadFailing) as exc:
                failed.append((u["v"], type(exc).__name__))
            if fm.calls:
                responded = u["v"]
                break
    finally:
        await inner.close()
    return responded, failed


async def test_a_healthy_bus_answers_the_crossing_at_31_s():
    responded, failed = await _respond_time("welfare.out", None)
    assert responded == 31.0
    assert failed == []


@pytest.mark.parametrize("stream", ["welfare.out", "interoception.out"])
@pytest.mark.parametrize(("mode", "error"), [("hang", "WelfareBusTimeout"), ("raise3", "WelfareBusReadFailing")])
async def test_a_failing_read_on_the_crossing_poll_still_answers_at_31_s(stream, mode, error):
    responded, failed = await _respond_time(stream, mode)
    assert responded == 31.0
    # The crossing poll still failed, so the liveness check sees it.
    assert (31.0, error) in failed


# --- the hang bounds (second review, re-verification 2: Q03, Q08-Q11) ----------------


async def test_q03_a_hung_record_publish_does_not_hang_the_poll():
    """Every publish hangs: the crossing poll still returns and the entity is preserved."""
    responded, failed = await _respond_time("welfare.out", None, hang_publish=True)
    assert responded == 31.0
    assert failed == []


def _indicator_monitor(bus, *, warmup_s: float) -> WelfareProtectiveMonitor:
    u = {"v": 0.0}
    return WelfareProtectiveMonitor(
        registry=ModuleRegistry(),
        fork_manager=_FM(),
        config=WelfareResponseConfig(enabled=True, warmup_s=warmup_s, warmup_ceiling_s=0.0),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=lambda: u["v"],
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=lambda: u["v"]
        ),
        bus_timeout_s=0.05,
    )


async def _hanging_on(stream: str) -> tuple[_Bus, AsyncBus]:
    inner = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=pytest.importorskip("fakeredis.aioredis").FakeRedis(decode_responses=True),
    )
    bus = _Bus(inner, stream, "hang")
    bus.bad = True
    return bus, inner


@pytest.mark.parametrize(
    ("warmup_s", "case"), [(0.0, "Q08 indicator arm"), (120.0, "Q11 warm-up accrual")]
)
async def test_a_hung_affect_read_fails_the_poll_at_once(warmup_s, case):
    """A timeout in the indicator arm is a failed poll for the liveness check
    (about 30 s), not a plain indicator error (660 s), in warm-up and after it."""
    bus, inner = await _hanging_on("affect.out")
    try:
        monitor = _indicator_monitor(bus, warmup_s=warmup_s)
        with pytest.raises(WelfareBusTimeout):
            await asyncio.wait_for(monitor._poll_once(asyncio.Event()), timeout=10.0)
    finally:
        await inner.close()


async def test_q09_a_hung_interoception_read_fails_its_first_poll():
    """A timeout on interoception.out fails the poll it happens in; it is not
    one of the three tolerated read failures."""
    bus, inner = await _hanging_on("interoception.out")
    try:
        monitor = _indicator_monitor(bus, warmup_s=0.0)
        monitor._indicators_on = False
        with pytest.raises(WelfareBusTimeout):
            await asyncio.wait_for(monitor._poll_once(asyncio.Event()), timeout=10.0)
    finally:
        await inner.close()


def test_q10_a_monitor_built_without_init_has_the_bound():
    monitor = object.__new__(WelfareProtectiveMonitor)
    assert monitor._bus_timeout_s == _WELFARE_BUS_TIMEOUT_S
    assert 0.0 < _WELFARE_BUS_TIMEOUT_S < 30.0
