# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Residency invariant: cognitive-cycle traces are identical between an
all-resident run and a multiplexed (residency-managed) run on the same
deterministic lockstep inputs, excluding timing.
"""

from __future__ import annotations

from typing import Any

import pytest

from kaine.bus.schema import Event
from kaine.cycle.engine import BASE_EPOCH, CognitiveCycle
from kaine.experiment import set_global_seed
from kaine.residency.events import clear_residency_events, residency_events
from kaine.residency.ledger import Ledger
from kaine.residency.router import ResidencyRouter
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticAffectModulator,
    StaticGoalScorer,
    Workspace,
)
from kaine.workspace.action_selection import ActionSelection
from tests._fakes import FakeClock

SEED = 1234
MIB = 1 << 20
GIB = 1 << 30


class ScriptedBus:
    def __init__(self, streams: dict[str, list[tuple[str, Event]]]) -> None:
        self._streams: dict[str, list[tuple[str, Event]]] = {
            name: list(entries) for name, entries in streams.items()
        }
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
        return f"{event.source}-pub"

    async def publish_workspace(self, snapshot: dict[str, Any], source: str = "workspace") -> str:
        self.workspace_broadcasts.append(snapshot)
        return "workspace-pub"

    async def close(self) -> None:
        return None

    async def current_workspace_id(self) -> str:
        return "0"

    def inject_entry(self, stream: str, event: Event) -> None:
        if stream not in self._streams:
            self._streams[stream] = []
        self._streams[stream].append((f"99-{len(self._streams[stream])}", event))


def _id_gt(entry_id: str, last_id: str) -> bool:
    if last_id in ("0", "0-0"):
        return True
    return _id_tuple(entry_id) > _id_tuple(last_id)


def _id_tuple(entry_id: str) -> tuple[int, int]:
    parts = entry_id.split("-")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return int(parts[0]), 0


class StreamRegistry:
    def __init__(self, streams: list[str]) -> None:
        self._streams = list(streams)

    def active_streams(self) -> list[str]:
        return list(self._streams)


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


def _build_cycle(
    bus: ScriptedBus,
    *,
    deterministic: bool = True,
    clock: FakeClock | None = None,
    lockstep: bool = True,
) -> CognitiveCycle:
    clk = clock if clock is not None else FakeClock()
    workspace = Workspace(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            affect_modulator=StaticAffectModulator(),
        ),
        top_k=5,
        publication_threshold=0.35,
    )
    return CognitiveCycle(
        bus=bus,
        workspace=workspace,
        registry=StreamRegistry(sorted(_scripted_streams().keys())),
        action_selection=ActionSelection(),
        clock=clk,
        sleep=clk.sleep,
        deterministic=deterministic,
        lockstep=lockstep,
        lockstep_timeout_s=60.0,
    )


async def _run_trajectory(*, n_ticks: int, seed: int) -> dict[str, Any]:
    set_global_seed(seed)
    bus = ScriptedBus(_scripted_streams())
    cycle = _build_cycle(bus)
    for _ in range(n_ticks):
        await cycle.tick()
    return {
        "broadcasts": [_normalize_broadcast(b) for b in bus.workspace_broadcasts],
        "intents": [_normalize_intent(e) for e in bus.published.get("action_selection", [])],
        "tick_stamps": [e.timestamp.isoformat() for e in bus.published.get("cycle", [])],
    }


async def _run_multiplexed_trajectory(*, n_ticks: int, seed: int) -> dict[str, Any]:
    set_global_seed(seed)
    bus = ScriptedBus(_scripted_streams())
    cycle = _build_cycle(bus)

    clear_residency_events()
    ledger = Ledger(budget_bytes=8 * GIB)
    router = ResidencyRouter(ledger)
    router.register("stt", footprint_bytes=400 * MIB)
    router.register("language", footprint_bytes=3 * GIB)
    router.register("tts", footprint_bytes=350 * MIB)
    router.register("sequence", footprint_bytes=100 * MIB)

    for _ in range(n_ticks):
        await router.before_load("stt", 400 * MIB)
        router.after_load("stt")
        router.record_use("stt")
        router.before_unload("stt")
        router.after_unload("stt")

        await router.before_load("language", 3 * GIB)
        router.after_load("language")
        router.record_use("language")

        await cycle.tick()

        router.before_unload("language")
        router.after_unload("language")

    return {
        "broadcasts": [_normalize_broadcast(b) for b in bus.workspace_broadcasts],
        "intents": [_normalize_intent(e) for e in bus.published.get("action_selection", [])],
        "tick_stamps": [e.timestamp.isoformat() for e in bus.published.get("cycle", [])],
    }


@pytest.mark.asyncio
async def test_all_resident_vs_multiplexed_identical_trace():
    n_ticks = 6
    run_a = await _run_trajectory(n_ticks=n_ticks, seed=SEED)
    run_b = await _run_multiplexed_trajectory(n_ticks=n_ticks, seed=SEED)

    assert run_a["broadcasts"] == run_b["broadcasts"]
    assert run_a["intents"] == run_b["intents"]
    assert run_a["tick_stamps"] == run_b["tick_stamps"]

    assert run_a["broadcasts"], "expected at least one broadcast"
    assert any(b["selected"] for b in run_a["broadcasts"]), "expected selections"
    assert run_a["intents"], "expected at least one intent"


@pytest.mark.asyncio
async def test_multiplexed_run_residency_events_fire():
    clear_residency_events()
    await _run_multiplexed_trajectory(n_ticks=3, seed=SEED)

    events = residency_events()
    kinds = {e.kind for e in events}
    assert "load_start" in kinds, "expected load_start events from residency router"
    assert "load_end" in kinds, "expected load_end events from residency router"
    assert "unload" in kinds, "expected unload events from residency router"
    assert len(events) >= 6, "expected multiple residency events across 3 ticks"


@pytest.mark.asyncio
async def test_invariant_holds_with_lockstep_participants():
    tick_done = Event(
        source="interoception",
        type="interoception.tick_done",
        payload={"tick": 0},
        salience=0.0,
        timestamp=BASE_EPOCH,
        tick=0,
        seq=0,
    )

    set_global_seed(SEED)
    bus_a = ScriptedBus(_scripted_streams())
    bus_a.inject_entry("interoception.out", tick_done)
    cycle_a = _build_cycle(bus_a)
    cycle_a.set_lockstep_participants(["interoception"])
    await cycle_a.tick()

    set_global_seed(SEED)
    bus_b = ScriptedBus(_scripted_streams())
    bus_b.inject_entry("interoception.out", tick_done)
    cycle_b = _build_cycle(bus_b)
    cycle_b.set_lockstep_participants(["interoception"])

    clear_residency_events()
    ledger = Ledger(budget_bytes=8 * GIB)
    router = ResidencyRouter(ledger)
    router.register("stt", footprint_bytes=400 * MIB)
    await router.before_load("stt", 400 * MIB)
    router.after_load("stt")
    router.record_use("stt")
    router.before_unload("stt")
    router.after_unload("stt")

    await cycle_b.tick()

    broadcasts_a = [_normalize_broadcast(b) for b in bus_a.workspace_broadcasts]
    broadcasts_b = [_normalize_broadcast(b) for b in bus_b.workspace_broadcasts]
    assert broadcasts_a == broadcasts_b
    assert broadcasts_a, "expected at least one broadcast with lockstep participants"


@pytest.mark.asyncio
async def test_timing_excluded_from_invariant():
    set_global_seed(SEED)
    bus_a = ScriptedBus(_scripted_streams())
    clock_a = FakeClock(start=0.0)
    cycle_a = _build_cycle(bus_a, clock=clock_a)

    set_global_seed(SEED)
    bus_b = ScriptedBus(_scripted_streams())
    clock_b = FakeClock(start=1000.0)
    cycle_b = _build_cycle(bus_b, clock=clock_b)

    for _ in range(3):
        await cycle_a.tick()
        await cycle_b.tick()

    norm_a = [_normalize_broadcast(b) for b in bus_a.workspace_broadcasts]
    norm_b = [_normalize_broadcast(b) for b in bus_b.workspace_broadcasts]
    assert norm_a == norm_b

    intents_a = [_normalize_intent(e) for e in bus_a.published.get("action_selection", [])]
    intents_b = [_normalize_intent(e) for e in bus_b.published.get("action_selection", [])]
    assert intents_a == intents_b

    assert norm_a, "expected broadcasts for timing exclusion test"
