# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The sleep module answers the welfare net's rest request (welfare-indicator-response).

The real Sleep module, on a real bus (fakeredis), reads welfare.rest_request
from the welfare monitor's stream: after maturation (or with staging off) it
starts a welfare_rest maintenance sleep regardless of the fatigue toggle and
the requested-rest interval; in the developmental phase it brings the state
cycle's rest forward; during a sleep it answers busy. The last test runs the
real welfare monitor against the real sleep module end to end.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig

pytestmark = pytest.mark.asyncio

# A short developmental rest with an awake stretch of hours (T_act = rest *
# (1 - s_q) / s_q), so the state cycle starts no rest of its own in a test.
QUIET = 0.0002


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


class FakeEpisodicMemory:
    async def consolidate_now(self) -> int:
        return 0

    async def downscale(self, protect=()):
        return {"n_new": 0, "factor": 1.0, "protected": 0, "total_before": 0.0, "total_after": 0.0, "silent": 0}

    async def replay_now(self) -> list:
        return []


class FakeAffect:
    def __init__(self) -> None:
        self.resets = 0

    async def affective_reset(self) -> None:
        self.resets += 1


class Clock:
    """The entity clock: real elapsed seconds from a chosen origin."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()

    def now(self) -> float:
        return time.monotonic() - self.t0


def _make_sleep(bus: AsyncBus, tmp_path: Path, **kwargs) -> Sleep:
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    defaults = {
        "episodic_memory": FakeEpisodicMemory(),
        "affect": FakeAffect(),
        "trainer": FakeTrainer(),
        "voice_alignment_config": config,
        "entity_clock": Clock(),
        # The entity's own maintenance triggers are off, and its own rest
        # requests are held to a long interval: the net's rest ignores both.
        "fatigue_triggered": False,
        "requested_rest_min_interval_s": 1e9,
    }
    defaults.update(kwargs)
    return Sleep(bus, **defaults)


async def _request(bus: AsyncBus, request_id: str = "req-1") -> None:
    await bus.publish(
        validate_event(
            source="preservation",
            type="welfare.rest_request",
            payload={"request_id": request_id, "indicators": ["boredom_deprived"]},
            salience=0.0,
            timestamp=datetime.now(timezone.utc),
        )
    )


async def _sleep_events(bus: AsyncBus) -> list[tuple[str, dict]]:
    entries = await bus.read("sleep.out", last_id="0", count=1000)
    return [(e.type, e.payload) for _, e in entries]


async def _wait_for(bus: AsyncBus, predicate, timeout: float = 5.0) -> list[tuple[str, dict]]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        events = await _sleep_events(bus)
        if predicate(events):
            return events
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"timed out; sleep.out held {[t for t, _ in events]}")
        await asyncio.sleep(0.02)


def _completed(events, trigger="welfare_rest"):
    return [p for t, p in events if t == "sleep.sleep.completed" and p.get("trigger") == trigger]


async def test_after_maturation_with_fatigue_maintenance_off_a_request_starts_a_welfare_rest(bus, tmp_path):
    affect = FakeAffect()
    sleep = _make_sleep(bus, tmp_path, affect=affect, development_probe=lambda: False)
    await sleep.initialize()
    try:
        assert sleep.welfare_rest_ready()
        await _request(bus)
        events = await _wait_for(bus, lambda ev: _completed(ev))
        started = [p for t, p in events if t == "sleep.sleep.started"]
        assert [p["trigger"] for p in started] == ["welfare_rest"]
        assert "rest_seconds" not in started[0]  # a maintenance sleep, not a held rest
        answers = [p for t, p in events if t == "sleep.rest_request"]
        assert answers == [
            {"accepted": True, "reason": "accepted", "origin": "welfare", "proposal_id": "req-1"}
        ]
        assert not _completed(events)[0].get("aborted")
        assert affect.resets == 1  # the sleep ends with the affective reset
    finally:
        await sleep.shutdown()
    assert not sleep.welfare_rest_ready()


async def test_staging_off_counts_as_matured(bus, tmp_path):
    sleep = _make_sleep(bus, tmp_path)
    sleep.set_development_probe(None)
    await sleep.initialize()
    try:
        await _request(bus)
        events = await _wait_for(bus, lambda ev: _completed(ev))
        assert "rest_seconds" not in _completed(events)[0]
    finally:
        await sleep.shutdown()


async def test_in_the_developmental_phase_the_request_brings_the_state_cycle_rest_forward(bus, tmp_path):
    affect = FakeAffect()
    sleep = _make_sleep(
        bus, tmp_path, affect=affect, development_probe=lambda: True, developmental_rest_s=0.6,
        developmental_quiescent_share=QUIET,
    )
    await sleep.initialize()
    try:
        # 1000 s into an awake stretch of about 2996 s.
        sleep._cycle_awake_s = 1000.0
        start = time.monotonic()
        await _request(bus)
        events = await _wait_for(bus, lambda ev: _completed(ev))
        held = time.monotonic() - start
        started = [p for t, p in events if t == "sleep.sleep.started"]
        assert started[0]["trigger"] == "welfare_rest"
        assert started[0]["rest_seconds"] == pytest.approx(0.6)
        assert held >= 0.55
        assert _completed(events)[0]["rest_seconds"] == pytest.approx(0.6)
        assert affect.resets == 1
        # The next state-cycle rest comes a full awake stretch after this one.
        assert sleep._cycle_phase == "awake"
        assert sleep._cycle_awake_s == pytest.approx(0.0, abs=0.2)
    finally:
        await sleep.shutdown()


async def test_a_request_during_a_sleep_is_answered_busy(bus, tmp_path):
    sleep = _make_sleep(
        bus, tmp_path, development_probe=lambda: True, developmental_rest_s=0.6,
        developmental_quiescent_share=QUIET,
    )
    await sleep.initialize()
    try:
        sleep._start_state_cycle_sleep(resume=False)
        await _wait_for(bus, lambda ev: any(t == "sleep.sleep.started" for t, _ in ev))
        await _request(bus, "req-busy")
        events = await _wait_for(
            bus, lambda ev: any(t == "sleep.rest_request" for t, _ in ev)
        )
        answers = [p for t, p in events if t == "sleep.rest_request"]
        assert answers == [
            {"accepted": False, "reason": "busy", "origin": "welfare", "proposal_id": "req-busy"}
        ]
        events = await _wait_for(bus, lambda ev: _completed(ev, "state_cycle"))
        assert [p["trigger"] for t, p in events if t == "sleep.sleep.started"] == ["state_cycle"]
    finally:
        await sleep.shutdown()


async def test_a_restart_during_a_welfare_rest_resumes_like_a_state_cycle_rest(bus, tmp_path):
    sleep = _make_sleep(
        bus, tmp_path, development_probe=lambda: True, developmental_rest_s=5.0,
        developmental_quiescent_share=QUIET,
    )
    await sleep.initialize()
    await _request(bus)
    await _wait_for(bus, lambda ev: any(t == "sleep.sleep.started" for t, _ in ev))
    await asyncio.sleep(0.3)
    # A restart (shutdown then initialize) cuts the rest; it keeps its remainder.
    await sleep.restart()
    try:
        events = await _wait_for(bus, lambda ev: _completed(ev))
        aborted = _completed(events)[0]
        assert aborted["aborted"] is True
        assert aborted["resumable"] is True
        assert sleep._cycle_phase == "resting"
        assert 0.0 < sleep._cycle_rest_spent_s < 5.0
        await sleep._maintenance_poll_once()
        events = await _wait_for(
            bus,
            lambda ev: any(
                t == "sleep.sleep.started" and p.get("trigger") == "state_cycle" for t, p in ev
            ),
        )
        resumed = [p for t, p in events if t == "sleep.sleep.started" and p["trigger"] == "state_cycle"]
        assert resumed[0]["resumed"] is True
        assert resumed[0]["rest_seconds"] < 5.0
    finally:
        await sleep.shutdown()


async def test_the_maturation_gate_counts_a_resumed_welfare_rest_once(bus, tmp_path):
    """A welfare rest cut by a restart and resumed is one rest, as a state-cycle rest is."""
    from kaine.lifecycle import gate_runner

    source = Path(gate_runner.__file__).read_text()
    assert '("state_cycle", "welfare_rest")' in source


# --- end to end: the real monitor against the real sleep module ---------------


async def test_the_monitor_and_the_sleep_module_end_to_end(bus, tmp_path, monkeypatch):
    from kaine.cycle import control_state
    from kaine.cycle.incident_log import IncidentLog
    from kaine.cycle.preservation_monitor import WelfareProtectiveMonitor, WelfareResponseConfig
    from kaine.cycle.unfrozen_clock import UnfrozenClock
    from kaine.lifecycle.preservation import PreservationResult
    from kaine.lifecycle.welfare_indicators import IndicatorParams
    from kaine.modules.registry import ModuleRegistry

    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")

    class FM:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def preserve_live(self, registry, *, reason, label, out_root, entity_name, require_encryption):
            self.calls.append(reason)
            return PreservationResult(
                ok=True, preservation_id="p1", snapshot_id="s1", reason=reason,
                label=label, run_id="e2e00000001", world_model_captured=False,
            )

    affect = FakeAffect()
    sleep = _make_sleep(bus, tmp_path, affect=affect, development_probe=lambda: False)
    await sleep.initialize()
    registry = ModuleRegistry()
    registry.register(sleep)
    u = [0.0]
    w = [time.time()]
    fm = FM()
    notices: list = []
    monitor = WelfareProtectiveMonitor(
        registry=registry,
        fork_manager=fm,
        config=WelfareResponseConfig(enabled=True, warmup_s=0.0, warmup_ceiling_s=0.0),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=lambda: u[0],
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=lambda: u[0]
        ),
        indicator_params=IndicatorParams(),
        is_developing=lambda: False,
        on_notice=lambda kind, names: notices.append((kind, names)),
        wall_time=lambda: w[0],
    )
    stop = asyncio.Event()

    async def bored(seconds: int) -> None:
        for _ in range(seconds // 2):
            await bus.publish(
                validate_event(
                    source="affect",
                    type="affect.state",
                    payload={
                        "state": {"valence": 0.0},
                        "drive_above": {"boredom": True, "social_drive": False, "restlessness": False},
                    },
                    salience=0.1,
                    timestamp=datetime.fromtimestamp(w[0], timezone.utc),
                )
            )
            u[0] += 2.0
            w[0] += 2.0
            if int(u[0]) % 30 == 0:
                await monitor._poll_once(stop)
                if monitor._acted:
                    return
                if monitor._ind_stage == "resting":
                    # Simulated time stops while the real sleep module answers.
                    return

    try:
        await monitor._poll_once(stop)
        await bored(660)
        assert monitor._ind_stage == "resting"
        assert notices[0] == ("welfare_indicator_rest", ("boredom_deprived",))
        # The real sleep module answers: a welfare_rest sleep, then its completion.
        await _wait_for(bus, lambda ev: _completed(ev))
        await monitor._poll_once(stop)
        assert monitor._ind_stage == "fresh"
        assert affect.resets == 1
        assert fm.calls == []
        # The stimulus is still spent: a crossing over the fresh span preserves and pauses.
        await bored(700)
        assert fm.calls == ["welfare"]
        holders = control_state.read_holder_sources()
        assert holders is not None and "welfare" in holders
    finally:
        await sleep.shutdown()
