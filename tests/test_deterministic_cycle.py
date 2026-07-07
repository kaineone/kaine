# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic cycle mode (the oscillatory-ablation keystone).

These tests prove that in deterministic mode the cognitive trajectory is a PURE
FUNCTION of the scripted input: two runs over the same scripted input produce an
identical cognitive trajectory — the same selected coalitions (entry_id, source,
type, salience), the same salience scores, the same inhibition decisions, the
same volition decisions, and the same *logical* event timestamps, tick by tick.
(The seed is pinned via `set_global_seed` for hygiene, but the rule-based
Syneidesis/Volition path samples nothing from it, so reproducibility here comes
from the scripted input and logical clock, NOT from the seed — see
`test_different_seeds_same_scripted_stimulus_documents_seed_independence`.)
Wall-clock latency fields (`wall_duration_ms`, `slip_ms`) are explicitly EXCLUDED
from the identity comparison — they are physical host measurements and are not
part of the reproducibility guarantee.

The harness drives the REAL `Syneidesis` (rule-based salience) and the REAL
`Volition` over a deterministic in-memory bus. The bus uses caller-supplied,
fixed entry ids so the selected-entry identity is meaningful across runs — a
time-based bus id (as Redis/fakeredis assigns) would be nondeterministic by
construction and would defeat the very property under test, so the harness
controls ids explicitly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from kaine.bus.schema import Event
from kaine.cycle.engine import BASE_EPOCH, CognitiveCycle
from kaine.experiment import set_global_seed
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)
from kaine.workspace.volition import Volition
from tests._fakes import FakeClock

SEED = 1234


# --------------------------------------------------------------------------
# Deterministic in-memory bus + scripted producer
# --------------------------------------------------------------------------


class ScriptedBus:
    """Minimal in-memory bus implementing exactly what the engine uses.

    Module streams are pre-seeded with caller-supplied, FIXED entry ids so that
    reading is reproducible across runs (unlike a time-based Redis id). Published
    events (workspace.broadcast and volition.out) are captured in order.
    """

    def __init__(self, streams: dict[str, list[tuple[str, Event]]]) -> None:
        # stream -> ordered [(entry_id, Event)] (entry_ids are caller-fixed).
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

    async def publish(self, event: Event) -> str:
        self.published.setdefault(event.source, []).append(event)
        return f"{event.source}-pub"

    async def publish_workspace(
        self, snapshot: dict[str, Any], source: str = "syneidesis"
    ) -> str:
        self.workspace_broadcasts.append(snapshot)
        return "workspace-pub"

    async def close(self) -> None:
        return None


def _id_gt(entry_id: str, last_id: str) -> bool:
    """Compare fixed string ids of the form '<n>-<m>'. '0' means 'from start'."""
    if last_id in ("0", "0-0"):
        return True
    return _id_tuple(entry_id) > _id_tuple(last_id)


def _id_tuple(entry_id: str) -> tuple[int, int]:
    parts = entry_id.split("-")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return int(parts[0]), 0


class StreamRegistry:
    """Registry exposing a fixed set of active streams (and no module phases)."""

    def __init__(self, streams: list[str]) -> None:
        self._streams = list(streams)

    def active_streams(self) -> list[str]:
        return list(self._streams)


def _make_event(source: str, etype: str, salience: float, text: str) -> Event:
    # Timestamp here is irrelevant to selection; the engine re-stamps published
    # events from its own clock. Use the fixed base epoch for tidiness.
    return Event(
        source=source,
        type=etype,
        payload={"text": text},
        salience=salience,
        timestamp=BASE_EPOCH,
    )


def _scripted_streams() -> dict[str, list[tuple[str, Event]]]:
    """A fixed, reproducible set of module streams with FIXED entry ids.

    Includes a user-communication event (audition.transcription) so the default
    volition policy emits a speak intent, plus competing events from other
    sources at varying salience, including an equal-salience pair to exercise
    the canonical tie-break.
    """
    return {
        "audition.out": [
            ("1-0", _make_event("audition", "audition.transcription", 0.62, "hello kaine")),
        ],
        "chronos.out": [
            ("1-0", _make_event("chronos", "chronos.tick", 0.50, "rhythm")),
        ],
        "soma.out": [
            ("1-0", _make_event("soma", "soma.state", 0.50, "interoception")),
        ],
        "topos.out": [
            ("1-0", _make_event("topos", "topos.place", 0.30, "here")),
        ],
    }


def _build_cycle(bus: ScriptedBus, *, deterministic: bool, clock=None) -> CognitiveCycle:
    syneidesis = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=5,
        publication_threshold=0.35,
    )
    return CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
        registry=StreamRegistry(sorted(_scripted_streams().keys())),
        volition=Volition(),
        clock=clock if clock is not None else FakeClock(),
        sleep=FakeClock().sleep,
        deterministic=deterministic,
    )


async def _run_trajectory(*, n_ticks: int, seed: int) -> dict[str, Any]:
    """Run the cycle for N ticks in deterministic mode and capture the
    trajectory (broadcasts + intents), excluding wall-clock latency fields."""
    set_global_seed(seed)
    bus = ScriptedBus(_scripted_streams())
    cycle = _build_cycle(bus, deterministic=True)
    for _ in range(n_ticks):
        await cycle.tick()
    return {
        "broadcasts": [_normalize_broadcast(b) for b in bus.workspace_broadcasts],
        "intents": [_normalize_intent(e) for e in bus.published.get("volition", [])],
        # Engine-published cycle.tick events stamped from _now() — the logical
        # clock in deterministic mode (excluding latency payload fields).
        "tick_stamps": [e.timestamp.isoformat() for e in bus.published.get("cycle", [])],
    }


def _normalize_broadcast(b: dict[str, Any]) -> dict[str, Any]:
    """Project a workspace broadcast to its determinism-relevant fields."""
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
# Keystone: two seeded runs produce identical trajectories
# (spec: "Two seeded runs produce identical trajectories")
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_seeded_runs_produce_identical_trajectory():
    """Fresh engine + same seed, twice → identical per-tick selected entries,
    salience scores, inhibited flags, volition decisions, and logical
    timestamps. Wall-clock latency (wall_duration_ms/slip_ms) is excluded
    because it never enters the captured trajectory at all."""
    n_ticks = 6
    run_a = await _run_trajectory(n_ticks=n_ticks, seed=SEED)
    run_b = await _run_trajectory(n_ticks=n_ticks, seed=SEED)

    assert run_a == run_b
    # The run is non-trivial: it actually selected and broadcast coalitions and
    # produced at least one intent — otherwise "identical" would be vacuous.
    assert run_a["broadcasts"], "expected at least one experiential broadcast"
    assert any(b["selected"] for b in run_a["broadcasts"]), "expected selections"
    assert run_a["intents"], "expected at least one volition intent"
    # And no wall-clock latency field leaked into the compared trajectory.
    for b in run_a["broadcasts"]:
        assert "wall_duration_ms" not in b and "slip_ms" not in b


@pytest.mark.asyncio
async def test_different_seeds_same_scripted_stimulus_documents_seed_independence():
    """Honest characterisation of WHAT the determinism guarantee covers.

    The keystone above proves SAME seed → SAME trajectory. A natural follow-up is
    "different seeds → different trajectories". But the scripted-stimulus harness
    here drives only the REAL `RuleBasedSalience` (novelty + static goal/thymos
    scorers) and the REAL rule-based `Volition` — none of which consult the global
    RNG. The salience scoring, canonical tie-break, inhibition, and volition
    policy are all deterministic FUNCTIONS of the input events; the seed feeds
    `set_global_seed` but no scored path samples from it on this fixed stimulus.

    So with this stimulus the trajectory is SEED-INDEPENDENT, and we assert that
    fact rather than fake a "different seeds differ" pass. The determinism
    guarantee the spec makes is "same seed + same scripted input → identical
    trajectory" (reproducibility), NOT "the seed perturbs the rule-based cognitive
    path" — there is no stochastic policy in this harness to perturb. A
    seed-dependent divergence would require a stochastic component (e.g. a sampled
    policy / dropout) that this scripted, rule-based path deliberately excludes.
    """
    n_ticks = 6
    run_seed_a = await _run_trajectory(n_ticks=n_ticks, seed=1)
    run_seed_b = await _run_trajectory(n_ticks=n_ticks, seed=999_999)
    # Different seeds, identical scripted stimulus → identical trajectory, because
    # no scored path on this stimulus draws from the seeded RNG.
    assert run_seed_a == run_seed_b
    # Non-trivial: there really was cognition to (not) perturb.
    assert run_seed_a["broadcasts"]
    assert any(b["selected"] for b in run_seed_a["broadcasts"])
    assert run_seed_a["intents"]


@pytest.mark.asyncio
async def test_exclusion_is_load_bearing_latency_would_differ():
    """Sanity: the wall-clock latency the guarantee EXCLUDES is genuinely
    nondeterministic (different injected monotonic clocks → different slip),
    so excluding it is load-bearing, not cosmetic."""
    set_global_seed(SEED)
    bus_a = ScriptedBus(_scripted_streams())
    clock_a = FakeClock()
    cycle_a = _build_cycle(bus_a, deterministic=True, clock=clock_a)

    # A clock whose elapsed time per tick is large → non-zero slip.
    class _SlowClock:
        def __init__(self) -> None:
            self._t = 0.0

        def __call__(self) -> float:
            self._t += 0.5  # 500ms between start/end reads → exceeds target
            return self._t

    set_global_seed(SEED)
    bus_b = ScriptedBus(_scripted_streams())
    cycle_b = _build_cycle(bus_b, deterministic=True, clock=_SlowClock())

    res_a = await cycle_a.tick()
    res_b = await cycle_b.tick()
    # Cognitive identity holds...
    assert _normalize_broadcast(bus_a.workspace_broadcasts[0]) == _normalize_broadcast(
        bus_b.workspace_broadcasts[0]
    )
    # ...even though the EXCLUDED latency differs.
    assert res_a.slip_ms != res_b.slip_ms


# --------------------------------------------------------------------------
# Logical clock (spec: "Logical timestamps in deterministic mode")
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logical_timestamps_equal_base_epoch_plus_tick_times_period():
    set_global_seed(SEED)
    bus = ScriptedBus(_scripted_streams())
    cycle = _build_cycle(bus, deterministic=True)
    period_s = 1.0 / cycle.processing_rate_hz

    for _ in range(5):
        await cycle.tick()

    # The engine stamps every event it PUBLISHES from _now(); in deterministic
    # mode that is the logical clock: tick k → BASE_EPOCH + k * period. The
    # cycle.tick latency event is published every tick, so its sequence pins the
    # per-tick logical timestamp directly.
    cycle_events = bus.published.get("cycle", [])
    assert len(cycle_events) == 5
    for i, ev in enumerate(cycle_events):
        assert ev.timestamp == BASE_EPOCH + timedelta(seconds=i * period_s)
    # Volition intents (also engine-published) carry the logical stamp of the
    # tick that produced them — a value strictly derived from the tick index.
    for ev in bus.published.get("volition", []):
        delta = ev.timestamp - BASE_EPOCH
        ticks = delta.total_seconds() / period_s
        assert abs(ticks - round(ticks)) < 1e-9, "intent stamp is a whole-tick logical time"


@pytest.mark.asyncio
async def test_logical_timestamps_identical_across_runs():
    run_a = await _run_trajectory(n_ticks=4, seed=SEED)
    run_b = await _run_trajectory(n_ticks=4, seed=SEED)
    # Engine-published (logical-clock-stamped) cycle.tick timestamps.
    assert run_a["tick_stamps"] == run_b["tick_stamps"]
    assert len(run_a["tick_stamps"]) == 4


# --------------------------------------------------------------------------
# Normal mode uses the injected wall clock
# (spec: "Real clock in normal mode")
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_mode_uses_injected_wall_clock():
    fixed = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
    calls = {"n": 0}

    def fake_wall_clock() -> datetime:
        calls["n"] += 1
        return fixed

    set_global_seed(SEED)
    bus = ScriptedBus(_scripted_streams())
    syneidesis = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=5,
        publication_threshold=0.35,
    )
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
        registry=StreamRegistry(sorted(_scripted_streams().keys())),
        volition=Volition(),
        clock=FakeClock(),
        sleep=FakeClock().sleep,
        wall_clock=fake_wall_clock,
        deterministic=False,
    )
    await cycle.tick()

    # The injected wall clock stamped the published cycle.tick latency event.
    cycle_events = bus.published.get("cycle", [])
    assert cycle_events, "expected a published cycle.tick event"
    assert cycle_events[0].timestamp == fixed
    assert calls["n"] >= 1
    # Default wall clock is real UTC (not the logical epoch) when not injected.
    assert not cycle.deterministic


@pytest.mark.asyncio
async def test_default_wall_clock_is_real_utc_not_logical():
    bus = ScriptedBus(_scripted_streams())
    cycle = _build_cycle(bus, deterministic=False)
    before = datetime.now(timezone.utc)
    stamp = cycle._now()
    after = datetime.now(timezone.utc)
    assert before <= stamp <= after
    assert stamp != BASE_EPOCH


# --------------------------------------------------------------------------
# Canonical within-tick event ordering
# (spec: "Tie-break is stable regardless of arrival order")
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_canonical_ordering_stable_tiebreak_regardless_of_arrival():
    """Equal-salience events from different sources, presented to the engine in
    two scrambled stream orders, select in the canonical (source, type,
    entry_id) order both times."""

    def equal_salience_streams() -> dict[str, list[tuple[str, Event]]]:
        return {
            "zeta.out": [("1-0", _make_event("zeta", "z.t", 0.6, "z"))],
            "alpha.out": [("1-0", _make_event("alpha", "a.t", 0.6, "a"))],
            "mid.out": [("1-0", _make_event("mid", "m.t", 0.6, "m"))],
        }

    async def run_with_stream_order(order: list[str]) -> list[tuple[str, str]]:
        set_global_seed(SEED)
        streams = equal_salience_streams()
        bus = ScriptedBus(streams)
        syneidesis = Syneidesis(
            strategy=RuleBasedSalience(
                novelty=NoveltyTracker(window=32),
                goal_scorer=StaticGoalScorer(),
                thymos_modulator=StaticThymosModulator(),
            ),
            top_k=5,
            publication_threshold=0.0,
        )
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=syneidesis,
            registry=StreamRegistry(order),
            volition=None,
            clock=FakeClock(),
            sleep=FakeClock().sleep,
            deterministic=True,
        )
        await cycle.tick()
        broadcast = bus.workspace_broadcasts[0]
        return [(s["source"], s["type"]) for s in broadcast["selected"]]

    scrambled_1 = await run_with_stream_order(["zeta.out", "alpha.out", "mid.out"])
    scrambled_2 = await run_with_stream_order(["mid.out", "zeta.out", "alpha.out"])

    expected = [("alpha", "a.t"), ("mid", "m.t"), ("zeta", "z.t")]
    assert scrambled_1 == expected
    assert scrambled_2 == expected


# --------------------------------------------------------------------------
# Default-off: existing behavior holds with deterministic=False
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_off_engine_constructs_with_real_defaults():
    bus = ScriptedBus(_scripted_streams())
    syneidesis = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=5,
        publication_threshold=0.35,
    )
    # No deterministic / wall_clock args at all → defaults.
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
        registry=StreamRegistry(sorted(_scripted_streams().keys())),
        volition=Volition(),
        clock=FakeClock(),
        sleep=FakeClock().sleep,
    )
    assert cycle.deterministic is False
    before = datetime.now(timezone.utc)
    await cycle.tick()
    after = datetime.now(timezone.utc)
    # Still produces a normal tick + broadcast.
    assert bus.workspace_broadcasts
    # The engine-published cycle.tick event is stamped from the (default real)
    # wall clock — not the logical epoch — when deterministic is off.
    cycle_events = bus.published.get("cycle", [])
    assert cycle_events, "expected a published cycle.tick event"
    stamp = cycle_events[0].timestamp
    assert before <= stamp <= after
    assert stamp != BASE_EPOCH
