# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Lockstep determinism, non-lockstep identity, and dilation stall tests (12.9).

Category A — two lockstep runs on the same scripted inputs, with different
random delays before each module's tick_done, produce identical normalised
traces and workspace contents.

Category B — existing determinism (lockstep off) stays green.

Category C — the TimeScaleController lowers scale under sustained stalls but
absorbs a single transient spike without a scale change.
"""
from __future__ import annotations

import asyncio
import random
from typing import Any

import pytest

from kaine.bus.schema import Event
from kaine.cycle.engine import BASE_EPOCH, CognitiveCycle
from kaine.cycle.time_scale_controller import TimeScaleController, TimeScaleSettings
from kaine.experiment import set_global_seed
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticAffectModulator,
    StaticGoalScorer,
    Workspace,
)
from kaine.workspace.action_selection import ActionSelection
from tests._fakes import FakeClock

# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

SEED = 1234


def _make_event(source: str, etype: str, salience: float, text: str) -> Event:
    return Event(
        source=source,
        type=etype,
        payload={"text": text},
        salience=salience,
        timestamp=BASE_EPOCH,
    )


def _scripted_streams() -> dict[str, list[tuple[str, Event]]]:
    return {
        "audition.out": [
            ("1-0", _make_event("audition", "audition.transcription", 0.62, "hello kaine")),
        ],
        "sequence.out": [
            ("1-0", _make_event("sequence", "sequence.tick", 0.50, "rhythm")),
        ],
        "interoception.out": [
            ("1-0", _make_event("interoception", "interoception.state", 0.50, "interoception")),
        ],
        "vision.out": [
            ("1-0", _make_event("vision", "vision.place", 0.30, "here")),
        ],
    }


PARTICIPANTS = ["audition", "sequence", "interoception", "vision"]


def _normalize_broadcast(b: dict[str, Any]) -> dict[str, Any]:
    return {
        "tick_index": b["tick_index"],
        "inhibited": b["inhibited"],
        "is_experiential": b["is_experiential"],
        "salience_scores": b["salience_scores"],
        "selected": [
            {
                "entry_id": s["entry_id"],
                "source": s["source"],
                "type": s["type"],
                "salience": s["salience"],
                "timestamp": s["timestamp"],
            }
            for s in b["selected"]
        ],
    }


def _normalize_intent(event: Event) -> dict[str, Any]:
    return {
        "source": event.source,
        "type": event.type,
        "payload": event.payload,
        "timestamp": event.timestamp.isoformat(),
    }


# --------------------------------------------------------------------------
# Lockstep-aware bus
# --------------------------------------------------------------------------


def _id_gt(entry_id: str, last_id: str) -> bool:
    if last_id in ("0", "0-0"):
        return True
    return _id_tuple(entry_id) > _id_tuple(last_id)


def _id_tuple(entry_id: str) -> tuple[int, int]:
    parts = entry_id.split("-")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return int(parts[0]), 0


class LockstepBus:
    """In-memory bus for lockstep determinism tests.

    Pre-seeded module events use fixed string IDs ("N-M") for reproducibility.
    When the engine publishes ``cycle.tick_start``, tick_done events are injected
    for every participant after an optional per-module delay (real asyncio sleep
    so the barrier polls pick them up).
    """

    def __init__(
        self,
        streams: dict[str, list[tuple[str, Event]]],
        participants: list[str],
        delay_rng: random.Random | None = None,
        max_delay: float = 0.005,
    ) -> None:
        self._streams: dict[str, list[tuple[str, Event]]] = {
            name: list(entries) for name, entries in streams.items()
        }
        self._participants = list(participants)
        self._delay_rng = delay_rng
        self._max_delay = max_delay
        self.workspace_broadcasts: list[dict[str, Any]] = []
        self.published: dict[str, list[Event]] = {}

    async def read(
        self, stream: str, last_id: str = "0", count: int = 100, block_ms: int = 0
    ) -> list[tuple[str, Event]]:
        entries = self._streams.get(stream, [])
        out: list[tuple[str, Event]] = []
        for entry_id, event in entries:
            if _id_gt(entry_id, last_id):
                out.append((entry_id, event))
            if len(out) >= count:
                break
        return out

    async def read_entries(
        self, stream: str, last_id: str = "0", count: int = 100, block_ms: int = 0
    ) -> tuple[list[tuple[str, Event]], str | None]:
        entries = await self.read(stream, last_id, count, block_ms)
        return entries, (entries[-1][0] if entries else None)

    async def publish(self, event: Event) -> str:
        self.published.setdefault(event.source, []).append(event)
        if event.type == "cycle.tick_start":
            await self._inject_tick_done(event.payload["tick"])
        return f"{event.source}-pub"

    async def publish_workspace(
        self, snapshot: dict[str, Any], source: str = "workspace"
    ) -> str:
        self.workspace_broadcasts.append(snapshot)
        return "workspace-pub"

    async def close(self) -> None:
        return None

    async def _inject_tick_done(self, tick: int) -> None:
        order = list(self._participants)
        if self._delay_rng is not None:
            self._delay_rng.shuffle(order)
        for name in order:
            if self._delay_rng is not None and self._max_delay > 0:
                await asyncio.sleep(self._delay_rng.random() * self._max_delay)
            stream = f"{name}.out"
            if stream not in self._streams:
                self._streams[stream] = []
            # Stable ID: based on tick + sorted participant index, not injection
            # order.  The barrier only cares about (type, payload.tick) matching,
            # but the workspace selection normalisation includes the entry_id in
            # salience_scores keys — a counter-based ID would differ across runs
            # with different delay seeds.
            pidx = sorted(self._participants).index(name)
            eid = f"{9000 + tick * 100 + pidx}-0"
            self._streams[stream].append((
                eid,
                Event(
                    source=name,
                    type=f"{name}.tick_done",
                    payload={"tick": tick},
                    salience=0.0,
                    timestamp=BASE_EPOCH,
                ),
            ))


class LockstepStreamRegistry:
    def __init__(self, streams: list[str]) -> None:
        self._streams = list(streams)

    def active_streams(self) -> list[str]:
        return list(self._streams)


# --------------------------------------------------------------------------
# Category A — lockstep determinism: two runs → identical traces
# --------------------------------------------------------------------------


def _build_lockstep_cycle(
    bus: LockstepBus,
    participants: list[str],
) -> CognitiveCycle:
    workspace = Workspace(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            affect_modulator=StaticAffectModulator(),
        ),
        top_k=5,
        publication_threshold=0.35,
    )
    cycle = CognitiveCycle(
        bus=bus,
        workspace=workspace,
        registry=LockstepStreamRegistry(sorted(_scripted_streams().keys())),
        action_selection=ActionSelection(),
        clock=FakeClock(),
        sleep=FakeClock().sleep,
        deterministic=True,
        lockstep=True,
        lockstep_timeout_s=5.0,
    )
    cycle.set_lockstep_participants(participants)
    return cycle


async def _run_lockstep_trajectory(
    *,
    n_ticks: int,
    seed: int,
    delay_seed: int,
    max_delay: float = 0.005,
) -> dict[str, Any]:
    set_global_seed(seed)
    delay_rng = random.Random(delay_seed)
    bus = LockstepBus(
        _scripted_streams(),
        PARTICIPANTS,
        delay_rng=delay_rng,
        max_delay=max_delay,
    )
    cycle = _build_lockstep_cycle(bus, PARTICIPANTS)
    await cycle.run_forever(max_ticks=n_ticks)
    return {
        "broadcasts": [_normalize_broadcast(b) for b in bus.workspace_broadcasts],
        "intents": [
            _normalize_intent(e)
            for e in bus.published.get("action_selection", [])
        ],
        "tick_stamps": [
            e.timestamp.isoformat()
            for e in bus.published.get("cycle", [])
            if e.type == "cycle.tick"
        ],
    }


@pytest.mark.asyncio
async def test_lockstep_two_runs_identical_traces():
    """Same scripted input, different random tick_done delays → identical
    normalised trajectory, proving lockstep eliminates timing nondeterminism."""
    n_ticks = 4
    run_a = await _run_lockstep_trajectory(
        n_ticks=n_ticks, seed=SEED, delay_seed=42, max_delay=0.005,
    )
    run_b = await _run_lockstep_trajectory(
        n_ticks=n_ticks, seed=SEED, delay_seed=9999, max_delay=0.005,
    )
    assert run_a == run_b
    assert run_a["broadcasts"], "expected at least one broadcast"
    assert any(b["selected"] for b in run_a["broadcasts"]), "expected selections"


@pytest.mark.asyncio
async def test_lockstep_runs_with_zero_vs_nonzero_delay_identical():
    """Even zero delay vs real delay produces the same trace."""
    n_ticks = 3
    run_zero = await _run_lockstep_trajectory(
        n_ticks=n_ticks, seed=SEED, delay_seed=1, max_delay=0.0,
    )
    run_slow = await _run_lockstep_trajectory(
        n_ticks=n_ticks, seed=SEED, delay_seed=1, max_delay=0.01,
    )
    assert run_zero == run_slow


# --------------------------------------------------------------------------
# Category B — non-lockstep determinism stays green
# --------------------------------------------------------------------------


async def _run_plain_trajectory(*, n_ticks: int, seed: int) -> dict[str, Any]:
    """Non-lockstep deterministic trajectory (same pattern as
    test_deterministic_cycle.py)."""
    from tests.test_deterministic_cycle import (
        ScriptedBus,
        StreamRegistry,
    )
    from tests.test_deterministic_cycle import (
        _normalize_broadcast as _det_norm_bc,
    )
    from tests.test_deterministic_cycle import (
        _normalize_intent as _det_norm_intent,
    )
    from tests.test_deterministic_cycle import (
        _scripted_streams as _det_streams,
    )

    set_global_seed(seed)
    bus = ScriptedBus(_det_streams())
    workspace = Workspace(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            affect_modulator=StaticAffectModulator(),
        ),
        top_k=5,
        publication_threshold=0.35,
    )
    cycle = CognitiveCycle(
        bus=bus,
        workspace=workspace,
        registry=StreamRegistry(sorted(_det_streams().keys())),
        action_selection=ActionSelection(),
        clock=FakeClock(),
        sleep=FakeClock().sleep,
        deterministic=True,
        lockstep=False,
    )
    for _ in range(n_ticks):
        await cycle.tick()
    return {
        "broadcasts": [_det_norm_bc(b) for b in bus.workspace_broadcasts],
        "intents": [_det_norm_intent(e) for e in bus.published.get("action_selection", [])],
        "tick_stamps": [e.timestamp.isoformat() for e in bus.published.get("cycle", [])],
    }


@pytest.mark.asyncio
async def test_non_lockstep_determinism_still_holds():
    """Two non-lockstep deterministic runs produce identical trajectories,
    confirming the lockstep code paths did not break the default path."""
    n = 6
    run_a = await _run_plain_trajectory(n_ticks=n, seed=SEED)
    run_b = await _run_plain_trajectory(n_ticks=n, seed=SEED)
    assert run_a == run_b
    assert run_a["broadcasts"], "expected broadcasts"
    assert run_a["intents"], "expected intents"


# --------------------------------------------------------------------------
# Category C — dilation: sustained stalls vs one short stall
# --------------------------------------------------------------------------


def _make_controller(
    dwell_s: float = 2.0,
    window_s: float = 5.0,
    ceiling: float = 2.0,
) -> TimeScaleController:
    return TimeScaleController(
        TimeScaleSettings(
            ceiling=ceiling,
            dwell_s=dwell_s,
            window_s=window_s,
            high=0.95,
            low=0.6,
            target=0.85,
        ),
        initial_scale=1.0,
    )


def test_sustained_stalls_drive_scale_down():
    """Many consecutive overloaded samples across more than dwell_s → the
    controller recommends a lower scale."""
    ctrl = _make_controller(dwell_s=2.0, window_s=5.0)
    period_ms = 100.0
    scale = 1.0
    change = None
    t = 0.0
    for i in range(30):
        t += 0.5
        result = ctrl.observe(
            busy_ms=period_ms,
            period_ms=period_ms,
            now_wall_s=t,
            current_scale=scale,
        )
        if result is not None:
            change = result
            scale = result.new

    assert change is not None, "sustained stalls should trigger a scale change"
    assert change.new < 1.0, f"scale should drop below 1.0, got {change.new}"
    assert change.reason == "overload"


def test_single_stall_does_not_change_scale():
    """One overloaded sample followed by normal utilisation → no scale change.
    The EMA + dwell_s threshold absorbs the transient."""
    ctrl = _make_controller(dwell_s=2.0, window_s=5.0)
    period_ms = 100.0
    scale = 1.0
    t = 0.0

    t += 0.5
    result = ctrl.observe(
        busy_ms=period_ms,
        period_ms=period_ms,
        now_wall_s=t,
        current_scale=scale,
    )
    assert result is None

    for _ in range(20):
        t += 0.5
        result = ctrl.observe(
            busy_ms=period_ms * 0.5,
            period_ms=period_ms,
            now_wall_s=t,
            current_scale=scale,
        )
        if result is not None:
            assert result.reason != "overload", (
                "a single stall followed by normal load should not trigger overload"
            )
