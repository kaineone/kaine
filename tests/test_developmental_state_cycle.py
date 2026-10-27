# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The developmental state cycle (change developmental-state-cycle, paper 3.5, Table A1).

In the developmental phase the sleep module alternates awake entity time T_act with a
rest of Delta_rest, trigger ``state_cycle``. Fatigue and the hourly backstop start no
sleep there; a maintenance request still does. After maturation, or with no probe, the
backstop and fatigue behave as before. The cycle survives a restart.

The cycle tests run a discrete-event simulation: ``asyncio.sleep`` advances a fake
entity clock, so a 1410 s rest takes no real time. The bus is fakeredis.
"""

from __future__ import annotations

import asyncio
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from kaine.boot.factories.sleep import make_sleep
from kaine.boot.wiring import _wire_affect_development
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.cycle.engine import CognitiveCycle
from kaine.dashboard.conversation import ConversationState
from kaine.modules.affect import Affect
from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig

REST_S = 1410.0
SHARE = 0.32
T_ACT = REST_S * (1.0 - SHARE) / SHARE  # 2996.25

_REAL_SLEEP = asyncio.sleep


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


class SimClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


class Probe:
    def __init__(self, value: bool = True) -> None:
        self.value = value

    def __call__(self) -> bool:
        return self.value


def _make(bus: AsyncBus, tmp_path: Path, clock: SimClock | None, probe: Any = None, **kwargs: Any) -> Sleep:
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    params: dict[str, Any] = {
        "episodic_memory": FakeEpisodicMemory(),
        "affect": FakeAffect(),
        "trainer": FakeTrainer(),
        "voice_alignment_config": config,
        "developmental_rest_s": REST_S,
        "developmental_quiescent_share": SHARE,
        "development_probe": probe,
        "entity_clock": clock,
    }
    params.update(kwargs)
    sleep = Sleep(bus, **params)
    return sleep


@pytest.fixture
def sim(monkeypatch):
    """A fake entity clock that every ``asyncio.sleep`` advances."""
    clock = SimClock()

    async def fake_sleep(delay: float, result: Any = None) -> Any:
        clock.t += max(0.0, float(delay))
        await _REAL_SLEEP(0)
        return result

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return clock


def _record(sleep: Sleep, clock: SimClock) -> list[tuple[float, str, dict[str, Any]]]:
    seen: list[tuple[float, str, dict[str, Any]]] = []
    original = sleep.publish

    async def recording(event_type: str, payload: dict[str, Any], **kwargs: Any) -> Any:
        seen.append((clock.t, event_type, dict(payload)))
        return await original(event_type, payload, **kwargs)

    sleep.publish = recording  # type: ignore[method-assign]
    return seen


async def _run(sleep: Sleep, clock: SimClock, until: float, step: float = 1.0) -> None:
    """Poll once per entity second until the clock reaches ``until``."""
    while clock.t < until:
        await sleep._maintenance_poll_once()
        if sleep.is_sleeping or sleep._sleep_pending:
            # The rest task advances the clock through its own sleeps.
            for _ in range(8):
                await _REAL_SLEEP(0)
        else:
            clock.t += step


def _starts(seen: list[Any], trigger: str | None = None) -> list[tuple[float, dict[str, Any]]]:
    return [
        (t, p)
        for t, kind, p in seen
        if kind == "sleep.sleep.started" and (trigger is None or p.get("trigger") == trigger)
    ]


def _ends(seen: list[Any]) -> list[tuple[float, dict[str, Any]]]:
    return [(t, p) for t, kind, p in seen if kind == "sleep.sleep.completed"]


def _event(source: str, type_: str, payload: dict[str, Any]) -> Any:
    return validate_event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.6,
        timestamp=datetime.now(timezone.utc),
    )


async def _wait_started(bus: AsyncBus, trigger: str, timeout: float = 2.0) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        for _, event in await bus.read("sleep.out", last_id="0", count=1000):
            if event.type == "sleep.sleep.started" and event.payload.get("trigger") == trigger:
                return event.payload
        if asyncio.get_running_loop().time() >= deadline:
            raise asyncio.TimeoutError(trigger)
        await _REAL_SLEEP(0.02)


# --- cycle timing -----------------------------------------------------------------


def test_awake_time_formula():
    assert T_ACT == pytest.approx(2996.25)


async def test_cycle_timing_on_a_fake_entity_clock(bus, tmp_path, sim):
    sleep = _make(bus, tmp_path, sim, Probe(True))
    seen = _record(sleep, sim)
    await _run(sleep, sim, 3 * T_ACT + 2 * REST_S + 20)
    starts = _starts(seen, "state_cycle")
    ends = _ends(seen)
    assert len(starts) >= 3 and len(ends) >= 2
    # The first rest comes after T_act of awake time (one poll of tolerance).
    assert starts[0][0] == pytest.approx(T_ACT, abs=2.0)
    assert starts[0][1]["rest_seconds"] == REST_S
    assert starts[0][1]["resumed"] is False
    # Each rest lasts 1410 s of entity time, then T_act awake again.
    assert ends[0][0] - starts[0][0] == pytest.approx(REST_S, abs=2.0)
    assert ends[0][1]["trigger"] == "state_cycle"
    assert ends[0][1]["rest_seconds"] == REST_S
    assert starts[1][0] - ends[0][0] == pytest.approx(T_ACT, abs=2.0)
    assert starts[2][0] - ends[1][0] == pytest.approx(T_ACT, abs=2.0)
    assert sleep._affect.resets >= 2


async def test_rest_runs_housekeeping_then_the_reset_after_the_hold(bus, tmp_path, sim):
    order: list[tuple[str, float]] = []

    class Housekeeper:
        async def run(self, episodic_store_bytes=None):
            order.append(("housekeeping", sim.t))
            return {"stopped": None, "moved_files": 0, "pressure": 0.0}

    affect = FakeAffect()
    original = affect.affective_reset

    async def reset() -> None:
        order.append(("reset", sim.t))
        await original()

    affect.affective_reset = reset  # type: ignore[method-assign]
    sleep = _make(bus, tmp_path, sim, Probe(True), housekeeper=Housekeeper(), affect=affect)
    seen = _record(sleep, sim)
    await _run(sleep, sim, T_ACT + REST_S + 10)
    began = _starts(seen, "state_cycle")[0][0]
    kinds = [k for k, _ in order]
    assert kinds == ["housekeeping", "reset"]
    assert order[0][1] - began >= REST_S - 1.0


# --- fatigue and the backstop -----------------------------------------------------


async def test_backstop_starts_no_sleep_in_the_phase(bus, tmp_path, sim):
    sleep = _make(bus, tmp_path, sim, Probe(True), interval_seconds=100.0)
    seen = _record(sleep, sim)
    await _run(sleep, sim, 500)
    assert sleep.is_due()  # the scheduler would fire the backstop
    assert _starts(seen) == []


async def test_backstop_fires_after_maturation_and_cycle_stops(bus, tmp_path, sim):
    probe = Probe(True)
    sleep = _make(bus, tmp_path, sim, probe, interval_seconds=100.0)
    seen = _record(sleep, sim)
    await _run(sleep, sim, 500)
    assert _starts(seen) == []
    probe.value = False
    await _run(sleep, sim, 590)
    assert [p["trigger"] for _, p in _starts(seen)] == ["backstop"]
    await _run(sleep, sim, 3 * T_ACT)
    assert _starts(seen, "state_cycle") == []


async def test_no_probe_behaves_as_before(bus, tmp_path, sim):
    sleep = _make(bus, tmp_path, sim, None, interval_seconds=100.0)
    seen = _record(sleep, sim)
    await _run(sleep, sim, 4 * T_ACT)
    assert _starts(seen, "state_cycle") == []
    assert _starts(seen, "backstop")


async def test_probe_that_raises_counts_as_developing(bus, tmp_path, sim):
    def boom() -> bool:
        raise RuntimeError("probe failure")

    sleep = _make(bus, tmp_path, sim, boom, interval_seconds=100.0)
    seen = _record(sleep, sim)
    await _run(sleep, sim, T_ACT + 10)
    assert [p["trigger"] for _, p in _starts(seen)] == ["state_cycle"]


async def _fatigue_run(bus, tmp_path, probe, wait_for: str | None) -> list[dict[str, Any]]:
    clock = SimClock()  # static: neither the cycle nor the backstop comes due
    sleep = _make(bus, tmp_path, clock, probe)
    await sleep.initialize()
    try:
        await bus.publish(_event("interoception", "interoception.fatigue", {"crossed": True}))
        if wait_for is not None:
            await _wait_started(bus, wait_for)
        else:
            await _REAL_SLEEP(0.4)
        return [
            e.payload
            for _, e in await bus.read("sleep.out", last_id="0", count=1000)
            if e.type == "sleep.sleep.started"
        ]
    finally:
        await sleep.shutdown()


async def test_fatigue_crossing_starts_no_sleep_in_the_phase(bus, tmp_path):
    assert await _fatigue_run(bus, tmp_path, Probe(True), None) == []


async def test_fatigue_crossing_still_sleeps_after_maturation(bus, tmp_path):
    started = await _fatigue_run(bus, tmp_path, Probe(False), "fatigue")
    assert [p["trigger"] for p in started] == ["fatigue"]


async def test_fatigue_crossing_still_sleeps_with_no_probe(bus, tmp_path):
    started = await _fatigue_run(bus, tmp_path, None, "fatigue")
    assert [p["trigger"] for p in started] == ["fatigue"]


async def test_maintenance_request_in_the_phase_still_sleeps(bus, tmp_path):
    clock = SimClock()
    sleep = _make(bus, tmp_path, clock, Probe(True))
    await sleep.initialize()
    try:
        await bus.publish(
            _event("interoception", "interoception.regulation", {"action": "request_maintenance"})
        )
        payload = await _wait_started(bus, "maintenance_request")
        assert payload["trigger"] == "maintenance_request"
    finally:
        await sleep.shutdown()


async def test_affect_maintenance_request_in_the_phase_still_sleeps(bus, tmp_path):
    clock = SimClock()
    sleep = _make(bus, tmp_path, clock, Probe(True))
    await sleep.initialize()
    try:
        await bus.publish(_event("affect", "affect.regulation", {"action": "request_maintenance"}))
        await _wait_started(bus, "affect_regulation")
    finally:
        await sleep.shutdown()


async def test_time_in_a_maintenance_sleep_is_not_awake_time(bus, tmp_path, sim):
    sleep = _make(bus, tmp_path, sim, Probe(True))
    await _run(sleep, sim, 1000)
    before = sleep._cycle_awake_s
    assert before == pytest.approx(1000.0, abs=2.0)
    # A maintenance sleep holds the lock for 300 s of entity time.
    await sleep._sleep_lock.acquire()
    try:
        for _ in range(300):
            sim.t += 1.0
            await sleep._maintenance_poll_once()
    finally:
        sleep._sleep_lock.release()
    assert sleep._cycle_awake_s == pytest.approx(before, abs=2.0)


# --- restart ----------------------------------------------------------------------


async def test_restart_mid_rest_resumes_for_the_remaining_time(bus, tmp_path, sim):
    first = _make(bus, tmp_path, sim, Probe(True))
    seen = _record(first, sim)
    await _run(first, sim, T_ACT + 10)
    assert first.is_sleeping or first._sleep_pending
    began = _starts(seen, "state_cycle")[0][0]
    await _run(first, sim, began + 600)
    # Shutdown cancels the running sleep and then serialises.
    first._sleep_task.cancel()
    await asyncio.gather(first._sleep_task, return_exceptions=True)
    aborted = [p for _, p in _ends(seen) if p.get("aborted")]
    assert aborted and aborted[0]["trigger"] == "state_cycle"
    state = first.serialize()
    assert state["state_cycle"]["phase"] == "resting"
    assert state["state_cycle"]["rest_spent_s"] == pytest.approx(600.0, abs=10.0)

    # A new process: a fresh clock at zero and the saved state.
    sim.t = 0.0
    second = _make(bus, tmp_path, sim, Probe(True))
    second.deserialize(state)
    seen2 = _record(second, sim)
    await _run(second, sim, 1500)
    starts = _starts(seen2, "state_cycle")
    ends = _ends(seen2)
    assert starts[0][0] == pytest.approx(0.0, abs=1.0)
    assert starts[0][1]["resumed"] is True
    assert starts[0][1]["rest_seconds"] == pytest.approx(REST_S - 600.0, abs=10.0)
    assert ends[0][0] == pytest.approx(REST_S - 600.0, abs=10.0)
    assert ends[0][1]["rest_seconds"] == pytest.approx(REST_S - 600.0, abs=10.0)
    # The awake stretch begins after the resumed rest.
    await _run(second, sim, ends[0][0] + T_ACT + 20)
    nxt = _starts(seen2, "state_cycle")[1]
    assert nxt[0] - ends[0][0] == pytest.approx(T_ACT, abs=2.0)
    assert nxt[1]["resumed"] is False


async def test_shutdown_during_a_rest_persists_the_remainder(bus, tmp_path, sim):
    sleep = _make(bus, tmp_path, sim, Probe(True))
    seen = _record(sleep, sim)
    await _run(sleep, sim, T_ACT + 10)
    began = _starts(seen, "state_cycle")[0][0]
    await _run(sleep, sim, began + 400)
    await sleep.shutdown()
    state = sleep.serialize()
    assert state["state_cycle"]["phase"] == "resting"
    assert state["state_cycle"]["rest_spent_s"] == pytest.approx(400.0, abs=10.0)


async def test_restart_mid_awake_keeps_the_spent_awake_time(bus, tmp_path, sim):
    first = _make(bus, tmp_path, sim, Probe(True))
    await _run(first, sim, 1000)
    state = first.serialize()
    assert state["state_cycle"]["phase"] == "awake"
    assert state["state_cycle"]["awake_s"] == pytest.approx(1000.0, abs=3.0)

    sim.t = 0.0
    second = _make(bus, tmp_path, sim, Probe(True))
    second.deserialize(state)
    seen = _record(second, sim)
    await _run(second, sim, T_ACT)
    first_rest = _starts(seen, "state_cycle")[0][0]
    assert first_rest == pytest.approx(T_ACT - 1000.0, abs=3.0)


async def test_restored_rest_waits_until_a_probe_says_developing(bus, tmp_path, sim):
    probe = Probe(False)
    sleep = _make(bus, tmp_path, sim, probe)
    sleep.deserialize({"state_cycle": {"phase": "resting", "awake_s": 0.0, "rest_spent_s": 100.0}})
    seen = _record(sleep, sim)
    await _run(sleep, sim, 10)
    assert _starts(seen) == []


async def test_malformed_state_cycle_in_a_snapshot_starts_fresh(bus, tmp_path):
    sleep = _make(bus, tmp_path, SimClock(), Probe(True))
    for bad in (
        "x",
        {"phase": "dozing", "awake_s": 1.0},
        {"phase": "awake", "awake_s": -5.0},
        {"phase": "awake", "awake_s": float("nan")},
        {"phase": "resting", "rest_spent_s": True},
    ):
        sleep.deserialize({"state_cycle": bad})
        assert sleep._cycle_phase == "awake" and sleep._cycle_awake_s == 0.0
    sleep.deserialize({"state_cycle": {"phase": "resting", "awake_s": 0.0, "rest_spent_s": REST_S + 5}})
    assert sleep._cycle_phase == "awake"
    sleep.deserialize({})  # an old snapshot with no cycle key


# --- affect: no rest request ------------------------------------------------------


def _affect(bus: AsyncBus, t: list[float], probe: Any) -> Affect:
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    affect._development_probe = probe
    affect._progress = lambda: (0.0, 0.0)
    affect._alert_excess = lambda: 0.0
    return affect


@pytest.mark.parametrize("probe", [lambda: True, lambda: False, None])
async def test_a_boredom_stall_publishes_no_rest_request_and_still_abandons(bus, probe):
    t = [0.0]
    affect = _affect(bus, t, probe)
    for _ in range(605):
        affect.drives.boredom.value = 0.95
        t[0] += 1.0
        await affect._tick()
    events = [e for _id, e in await bus.read("affect.out", last_id="0", count=5000)]
    assert [e for e in events if e.type == "affect.rest_request"] == []
    stalled = [
        e
        for e in events
        if e.type == "affect.goal"
        and e.payload.get("action") == "abandoned"
        and e.payload.get("reason") == "stalled"
    ]
    assert stalled


async def test_affect_snapshot_has_no_engagement_field_and_old_one_restores(bus):
    t = [50.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    state = affect.serialize()
    assert "boredom_engaged_elapsed" not in state
    for old in (12.5, None, "x", True, -1.0):
        fresh = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
        fresh.deserialize({**state, "boredom_engaged_elapsed": old})
        assert not hasattr(fresh, "_boredom_engaged_at")
        assert not hasattr(fresh, "_rest_requests")


# --- configuration ----------------------------------------------------------------


def test_share_validation_in_the_module(bus):
    for bad in (0, 0.0, 1, 1.0, -0.1, 1.5, float("nan"), float("inf"), True, "0.3"):
        with pytest.raises(ValueError, match="developmental_quiescent_share"):
            Sleep(bus, developmental_quiescent_share=bad)
    sleep = Sleep(bus, developmental_quiescent_share=0.5, developmental_rest_s=100.0)
    assert sleep._developmental_awake_s == pytest.approx(100.0)


def test_share_validation_in_the_factory(bus):
    for bad in (0, 1, -1, 2, float("nan"), True, "x"):
        with pytest.raises(ValueError, match="developmental_quiescent_share"):
            make_sleep(bus, {"developmental_quiescent_share": bad})
    made = make_sleep(bus, {"developmental_quiescent_share": 0.25})
    assert made._developmental_quiescent_share == 0.25


def test_defaults_follow_table_a1(bus):
    sleep = Sleep(bus)
    assert sleep._developmental_rest_s == 1410.0
    assert sleep._developmental_quiescent_share == 0.32
    root = Path(__file__).resolve().parents[1]
    section = tomllib.loads((root / "config" / "kaine.toml").read_text())["sleep"]
    assert section["developmental_rest_s"] == 1410.0
    assert section["developmental_quiescent_share"] == 0.32
    made = make_sleep(bus, section)
    assert made._developmental_awake_s == pytest.approx(T_ACT)


def test_wiring_gives_the_sleep_module_the_probe():
    class Registry:
        def __init__(self) -> None:
            self.modules: dict[str, Any] = {}

        def __contains__(self, name: str) -> bool:
            return name in self.modules

        def get(self, name: str) -> Any:
            return self.modules[name]

    class Holder:
        probe = None

        def set_development_probe(self, probe: Any) -> None:
            self.probe = probe

    registry = Registry()
    registry.modules["sleep"] = Holder()
    registry.modules["affect"] = Holder()

    def probe() -> bool:
        return True

    _wire_affect_development(registry, probe)  # type: ignore[arg-type]
    assert registry.modules["sleep"].probe is probe
    replacement = Holder()
    registry.modules["sleep"] = replacement
    _wire_affect_development(registry)  # type: ignore[arg-type]
    assert replacement.probe is probe


# --- dashboard --------------------------------------------------------------------


def test_dashboard_shows_the_state_cycle_rest_and_its_length():
    state = ConversationState()
    state.observe(
        _event("sleep", "sleep.sleep.started", {"trigger": "state_cycle", "started_at": 1000.0, "rest_seconds": REST_S})
    )
    snap = state.sleep_snapshot()
    assert snap["sleep"]["trigger"] == "state_cycle"
    assert snap["sleep"]["rest_seconds"] == REST_S
    state.observe(
        _event(
            "sleep",
            "sleep.sleep.completed",
            {"trigger": "state_cycle", "rest_seconds": REST_S, "total_elapsed_ms": 1500.0},
        )
    )
    snap = state.sleep_snapshot()
    assert snap["sleep"]["trigger"] == "state_cycle"
    assert snap["sleep"]["rest_seconds"] == REST_S
    js = (Path(__file__).resolve().parents[1] / "kaine" / "dashboard" / "static" / "dashboard_sleep.js").read_text()
    assert 'state_cycle: "state-cycle rest"' in js
    assert 'developmental_rest: "developmental rest (earlier rule)"' in js


# --- welfare: a rest counts as time not awake --------------------------------------


class _Hooks:
    async def fire(self, name: str, **kwargs: Any) -> None:
        return


async def test_a_rest_hold_counts_as_time_not_awake(bus, tmp_path, sim):
    """The cycle's unawake total, which lived time, the development owner and the maturation
    gate subtract, takes in the whole 1410 s hold."""
    sleep = _make(bus, tmp_path, sim, Probe(True))
    cycle = object.__new__(CognitiveCycle)
    cycle._paused = asyncio.Event()
    cycle._paused.set()
    cycle._paused_total = 0.0
    cycle._paused_at = None
    cycle._sleep_source = None
    cycle._unawake_total = 0.0
    cycle._unawake_since = None
    cycle._entity_clock = sim
    cycle.hooks = _Hooks()
    cycle.set_sleep_source(lambda: sleep.is_sleeping)
    seen = _record(sleep, sim)

    asleep_flags: list[bool] = []
    original = sleep._hold_developmental_rest

    async def watching(started: float) -> None:
        asleep_flags.append(cycle.is_asleep)
        cycle.unawake_subjective_seconds()  # the cycle refreshes this on every tick
        await original(started)

    sleep._hold_developmental_rest = watching  # type: ignore[method-assign]
    while not _ends(seen):
        await _run(sleep, sim, sim.t + 1.0)
    for _ in range(8):
        await _REAL_SLEEP(0)
    unawake = cycle.unawake_subjective_seconds()
    assert asleep_flags == [True]
    assert unawake == pytest.approx(REST_S, abs=3.0)
    assert not cycle.is_asleep
    # Awake time afterwards adds nothing.
    sim.t += 500.0
    assert cycle.unawake_subjective_seconds() == pytest.approx(unawake)


# --- frozen time and shutdown -------------------------------------------------------


class Frozen:
    """A paused-seconds source: the entity clock runs on while the cycle is frozen."""

    def __init__(self) -> None:
        self.total = 0.0

    def __call__(self) -> float:
        return self.total


async def test_frozen_time_does_not_count_toward_the_awake_stretch(bus, tmp_path, sim):
    frozen = Frozen()
    sleep = _make(bus, tmp_path, sim, Probe(True))
    sleep.set_paused_source(frozen)
    seen = _record(sleep, sim)
    await _run(sleep, sim, 1000)
    sim.t += 500.0  # a freeze of 500 s
    frozen.total += 500.0
    await _run(sleep, sim, T_ACT + 600)
    assert _starts(seen, "state_cycle")[0][0] == pytest.approx(T_ACT + 500.0, abs=3.0)


async def test_frozen_time_extends_a_rest(bus, tmp_path, sim):
    frozen = Frozen()
    sleep = _make(bus, tmp_path, sim, Probe(True))
    sleep.set_paused_source(frozen)
    seen = _record(sleep, sim)
    await _run(sleep, sim, T_ACT + 10)
    began = _starts(seen, "state_cycle")[0][0]
    await _run(sleep, sim, began + 300)
    sim.t += 200.0  # frozen during the rest
    frozen.total += 200.0
    while not _ends(seen):
        await _run(sleep, sim, sim.t + 1.0)
    assert _ends(seen)[0][0] - began == pytest.approx(REST_S + 200.0, abs=3.0)


async def test_shutdown_during_a_rest_ends_it_aborted_without_completing_the_schedule(bus, tmp_path, sim):
    sleep = _make(bus, tmp_path, sim, Probe(True))
    seen = _record(sleep, sim)
    marked: list[float] = []
    sleep.scheduler.mark_completed = lambda: marked.append(sim.t)  # type: ignore[method-assign]
    await _run(sleep, sim, T_ACT + 10)
    began = _starts(seen, "state_cycle")[0][0]
    await _run(sleep, sim, began + 400)
    sleep._stopped.set()  # BaseModule.shutdown sets this before it cancels the task
    for _ in range(20):
        await _REAL_SLEEP(0)
    ends = _ends(seen)
    assert len(ends) == 1 and ends[0][1]["aborted"] is True
    assert ends[0][1]["trigger"] == "state_cycle"
    assert marked == []
    assert sleep._affect.resets == 1
    state = sleep.serialize()["state_cycle"]
    assert state["phase"] == "resting"
    assert state["rest_spent_s"] == pytest.approx(400.0, abs=10.0)


async def test_hold_sleeps_less_real_time_at_high_time_scale(bus, tmp_path, monkeypatch):
    class Fast(SimClock):
        scale = 4.0

    clock = Fast()
    delays: list[float] = []

    async def fake_sleep(delay: float, result: Any = None) -> Any:
        delays.append(delay)
        clock.t += delay * 4.0
        await _REAL_SLEEP(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    sleep = _make(bus, tmp_path, clock, Probe(True), developmental_rest_s=10.0)
    await sleep._hold_developmental_rest(clock.t)
    assert clock.t == pytest.approx(10.0, abs=0.01)  # no overshoot
    assert max(delays) <= 1.0


async def test_probe_failure_is_logged_once(bus, tmp_path, caplog):
    def boom() -> bool:
        raise RuntimeError("x")

    sleep = _make(bus, tmp_path, SimClock(), boom)
    for _ in range(5):
        assert sleep._developing() is True
    assert len([r for r in caplog.records if "development probe failed" in r.getMessage()]) == 1


# --- welfare observer, gate count, interoception latch, supervisor, probe wait ---------


class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def write(self, entry: dict[str, Any]) -> None:
        self.rows.append(entry)


async def test_unmaintained_fatigue_alarm_is_off_in_the_phase_through_a_full_rest(bus, tmp_path, sim):
    from kaine.evaluation.observers.welfare_observer import WelfareObserver

    probe = Probe(True)
    sink = _Sink()
    obs = WelfareObserver(bus, sink, maintenance_window_s=900.0, unfrozen_clock=sim, development_probe=probe)
    sleep = _make(bus, tmp_path, sim, probe)
    seen = _record(sleep, sim)
    crossing = _event("interoception", "interoception.fatigue", {"value": 105.0, "threshold": 100.0})
    fed = 0

    async def feed_sleep_events() -> None:
        nonlocal fed
        while fed < len(seen):
            _, kind, payload = seen[fed]
            fed += 1
            if kind.startswith("sleep.sleep."):
                await obs._handle_sleep("1-0", _event("sleep", kind, payload))

    # A crossing early in the awake stretch, which no sleep answers, and another mid-rest.
    await _run(sleep, sim, 100)
    await obs._handle_interoception("1-0", crossing)
    for _ in range(3):
        await _run(sleep, sim, sim.t + 400)
        await feed_sleep_events()
        await obs._check_timed_conditions()
    while not _ends(seen):
        await _run(sleep, sim, sim.t + 100)
        await feed_sleep_events()
        if sleep.is_sleeping:
            await obs._handle_interoception("2-0", crossing)
        await obs._check_timed_conditions()
    assert _starts(seen, "state_cycle")
    assert obs.unmaintained_fatigue_count == 0
    assert sink.rows == []

    # After maturation a crossing no sleep answers raises the alarm as before.
    probe.value = False
    await obs._handle_interoception("3-0", crossing)
    sim.t += 1000.0
    await obs._check_timed_conditions()
    assert obs.unmaintained_fatigue_count == 1


async def test_the_preservation_repeat_arm_sees_no_fatigue_event_in_the_phase(bus, sim):
    from kaine.cycle.preservation_monitor import WelfareProtectiveMonitor
    from kaine.evaluation.observers.welfare_observer import WelfareObserver
    from kaine.lifecycle.welfare_signal import WindowedEventCounter

    crossing = _event("interoception", "interoception.fatigue", {"value": 105.0, "threshold": 100.0})
    for developing, expected in ((True, []), (False, ["repeated_gray_zone"])):
        probe = Probe(developing)
        obs = WelfareObserver(bus, _Sink(), maintenance_window_s=900.0, unfrozen_clock=sim, development_probe=probe)
        await obs._handle_interoception("1-0", crossing)
        sim.t += 1000.0
        await obs._check_timed_conditions()
        monitor = object.__new__(WelfareProtectiveMonitor)
        monitor._bus = bus
        monitor._welfare_cursor = "0"
        monitor._clock = lambda: sim.t
        monitor._repeat = WindowedEventCounter(window_s=300.0, threshold=1)
        assert await monitor._drain_gray_zone() == expected


async def test_fatigue_alarm_without_a_probe_is_unchanged(bus):
    from kaine.evaluation.observers.welfare_observer import WelfareObserver

    clock = SimClock()
    obs = WelfareObserver(bus, _Sink(), maintenance_window_s=900.0, unfrozen_clock=clock)
    await obs._handle_interoception("1-0", _event("interoception", "interoception.fatigue", {}))
    clock.t = 1000.0
    await obs._check_timed_conditions()
    assert obs.unmaintained_fatigue_count == 1


async def test_a_resumed_rest_counts_once_toward_the_sleep_cycles(bus):
    from dataclasses import replace

    from kaine.lifecycle.gate_runner import MaturationGateRunner
    from kaine.lifecycle.stage import DEVELOPMENT, StageState

    for payload in (
        {"trigger": "state_cycle", "aborted": True, "reason": "CancelledError", "rest_seconds": REST_S},
        {"trigger": "state_cycle", "rest_seconds": 810.0},
        {"trigger": "backstop"},
        {"trigger": "fatigue", "aborted": True, "reason": "CancelledError"},
        {"trigger": "state_cycle", "aborted": True, "reason": "RuntimeError", "rest_seconds": REST_S},
    ):
        await bus.publish(_event("sleep", "sleep.sleep.completed", payload))
    runner = object.__new__(MaturationGateRunner)
    runner._bus = bus
    runner._sleep_stream = "sleep.out"
    runner._stage = replace(StageState(stage=DEVELOPMENT), sleep_cursor="0-0", sleep_count=0)
    await runner._count_new_sleeps()
    # The cancelled state-cycle completion counts nothing; a failed one does, as it never resumes.
    assert runner._stage.sleep_count == 4


def test_maturation_clears_the_interoception_fatigue_latch():
    from kaine.modules.interoception.module import Interoception

    module = object.__new__(Interoception)
    probe = Probe(True)
    module._development_probe = probe
    module._was_developing = False
    module._fatigue_threshold_emitted = True
    module._check_maturation()
    assert module._fatigue_threshold_emitted is True  # still in the phase
    probe.value = False
    module._check_maturation()
    assert module._fatigue_threshold_emitted is False
    module._fatigue_threshold_emitted = True
    module._check_maturation()
    assert module._fatigue_threshold_emitted is True  # only the flip clears it


def test_wiring_gives_interoception_the_probe():
    class Registry:
        def __init__(self) -> None:
            self.modules: dict[str, Any] = {}

        def __contains__(self, name: str) -> bool:
            return name in self.modules

        def get(self, name: str) -> Any:
            return self.modules[name]

    class Holder:
        probe: Any = "unset"

        def set_development_probe(self, probe: Any) -> None:
            self.probe = probe

    registry = Registry()
    registry.modules["interoception"] = Holder()
    registry.modules["sleep"] = Holder()
    _wire_affect_development(registry, Probe(True))  # type: ignore[arg-type]
    assert registry.modules["interoception"].probe is not None
    plain = Registry()
    plain.modules["sleep"] = Holder()
    _wire_affect_development(plain)  # type: ignore[arg-type]
    assert plain.modules["sleep"].probe is None  # an explicit "no probe" is still wired


async def test_backstop_waits_until_the_probe_is_wired(bus, tmp_path, sim):
    sleep = _make(bus, tmp_path, sim, None, interval_seconds=100.0, await_development_probe=True)
    seen = _record(sleep, sim)
    await _run(sleep, sim, 500)
    assert sleep.is_due() and _starts(seen) == []
    sleep.set_development_probe(None)  # staging off: the phase is known to be absent
    await _run(sleep, sim, 520)
    assert [p["trigger"] for _, p in _starts(seen)] == ["backstop"]


async def test_backstop_stays_off_when_the_wired_probe_says_developing(bus, tmp_path, sim):
    sleep = _make(bus, tmp_path, sim, None, interval_seconds=100.0, await_development_probe=True)
    seen = _record(sleep, sim)
    await _run(sleep, sim, 500)
    sleep.set_development_probe(Probe(True))
    await _run(sleep, sim, 520)
    assert _starts(seen, "backstop") == []


def test_the_factory_waits_for_the_probe(bus):
    assert make_sleep(bus, {})._await_development_probe is True


async def test_a_completed_maintenance_sleep_restarts_the_active_stretch(bus, tmp_path, sim):
    sleep = _make(bus, tmp_path, sim, Probe(True))
    seen = _record(sleep, sim)
    await _run(sleep, sim, 2900)
    assert sleep._cycle_awake_s > 2800
    await sleep.enter_sleep(trigger="maintenance_request")
    assert sleep._cycle_awake_s == 0.0
    done = sim.t
    await _run(sleep, sim, done + T_ACT + 20)
    assert _starts(seen, "state_cycle")[0][0] - done == pytest.approx(T_ACT, abs=3.0)


async def test_an_aborted_sleep_does_not_restart_the_active_stretch(bus, tmp_path, sim):
    sleep = _make(bus, tmp_path, sim, Probe(True))
    await _run(sleep, sim, 1000)

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("phase failure")

    sleep._run_voice_alignment = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await sleep.enter_sleep(trigger="maintenance_request")
    assert sleep._cycle_awake_s == pytest.approx(1000.0, abs=3.0)


async def test_hold_reads_the_clock_scale_on_each_iteration(bus, tmp_path, monkeypatch):
    class Shifting(SimClock):
        scale = 1.0

    clock = Shifting()

    async def fake_sleep(delay: float, result: Any = None) -> Any:
        clock.t += delay * clock.scale
        if clock.t > 3.0:
            clock.scale = 4.0
        await _REAL_SLEEP(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    sleep = _make(bus, tmp_path, clock, Probe(True), developmental_rest_s=10.0)
    await sleep._hold_developmental_rest(clock.t)
    assert clock.t == pytest.approx(10.0, abs=0.01)


async def _supervisor_for(sleep: Sleep, rebuilt: list[Sleep], probe: Probe):
    from kaine.cycle.supervisor import Supervisor
    from kaine.modules.registry import ModuleRegistry

    registry = ModuleRegistry()
    registry.register(sleep)
    registry.affect_development_probe = probe  # type: ignore[attr-defined]
    supervisor = object.__new__(Supervisor)
    supervisor._registry = registry
    supervisor._kaine_config = {}
    supervisor._incidents = {}
    supervisor._fork_manager = None
    supervisor._rebuild_module = lambda name: rebuilt[0]
    return supervisor, registry


async def test_a_supervisor_restart_keeps_the_awake_time(bus, tmp_path):
    clock = SimClock()
    probe = Probe(True)
    old = _make(bus, tmp_path, clock, probe, await_development_probe=True)
    old._cycle_awake_s = 1234.0
    new = _make(bus, tmp_path, clock, None, await_development_probe=True)
    supervisor, registry = await _supervisor_for(old, [new], probe)
    try:
        result = await supervisor._restart_module("sleep")
        assert result.ok and registry.get("sleep") is new
        assert new._cycle_phase == "awake"
        assert new._cycle_awake_s == pytest.approx(1234.0)
        assert new._await_development_probe is False  # rewired with the stored probe
    finally:
        await new.shutdown()


async def test_a_supervisor_restart_resumes_a_cut_rest(bus, tmp_path):
    clock = SimClock()
    probe = Probe(True)
    old = _make(bus, tmp_path, clock, probe, await_development_probe=True)
    old._cycle_phase = "resting"
    old._cycle_rest_spent_s = 600.0
    new = _make(bus, tmp_path, clock, None, await_development_probe=True)
    supervisor, registry = await _supervisor_for(old, [new], probe)
    try:
        result = await supervisor._restart_module("sleep")
        assert result.ok
        payload = await _wait_started(bus, "state_cycle", timeout=5.0)
        assert payload["resumed"] is True
        assert payload["rest_seconds"] == pytest.approx(REST_S - 600.0)
    finally:
        await new.shutdown()


def test_the_research_taxonomy_drops_the_dead_rest_request_and_names_the_rest_fields():
    from kaine.evaluation.observers.research_event_observer import _TAXONOMY

    assert "affect.rest_request" not in _TAXONOMY
    assert {"rest_seconds", "resumed"} <= _TAXONOMY["sleep.sleep.started"]


def test_boot_wires_the_phase_before_any_module_initializes():
    import inspect

    from kaine.cycle import __main__ as cycle_main

    source = inspect.getsource(cycle_main._phase_registry)
    assert source.index("_wire_development(ctx)") < source.index("await module.initialize()")
