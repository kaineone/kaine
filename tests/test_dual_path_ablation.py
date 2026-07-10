# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live oscillatory ablation: Syneidesis.select_dual + selection_delta.

The load-bearing invariants: on an experiential tick the dual-path pass returns
(primary, counterfactual) where the primary is BYTE-IDENTICAL to what
``select()`` produces (so enabling the ablation never changes the entity's
behaviour) and the counterfactual is exactly the coherence-OFF baseline (so the
two arms differ by the layer alone) — the paired, same-stimulus contrast the
ablation needs, recovered live without replaying a stimulus.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)
from kaine.workspace.coherence import CoherenceScorer
from kaine.workspace.syneidesis import selection_delta


def _ev(intensity: float, eid: str, source: str) -> tuple[str, Event]:
    return eid, Event(
        source=source,
        type=f"t.{eid}",
        payload={"id": eid},
        salience=intensity,
        timestamp=datetime.now(timezone.utc),
    )


def _strategy() -> RuleBasedSalience:
    return RuleBasedSalience(
        novelty=NoveltyTracker(window=64),
        goal_scorer=StaticGoalScorer(),
        thymos_modulator=StaticThymosModulator(),
    )


def _scorer() -> CoherenceScorer:
    return CoherenceScorer(plv_window=12, coherence_floor=0.5, coherence_ceiling=1.5)


def _batch(seed: int = 7):
    rng = random.Random(seed)
    sources = ["soma", "chronos", "topos", "thymos"]
    events = [
        _ev(round(rng.uniform(0.1, 0.95), 4), f"e{i}", sources[i]) for i in range(4)
    ]
    ctx = {
        "tick_index": 0,
        "phases": {s: rng.uniform(0.0, 2 * math.pi) for s in sources},
    }
    return events, ctx


def _ids(snap: WorkspaceSnapshot) -> list[str]:
    return [eid for eid, _ in snap.selected_events]


# --------------------------------------------------------------------------- #
# select_dual — the two invariants
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_primary_is_identical_to_coherence_on_select():
    """The primary arm equals what a coherence-ON select() produces, so enabling
    the ablation does not change the entity's behaviour."""
    events, ctx = _batch()
    dual = Syneidesis(
        strategy=_strategy(), top_k=3, publication_threshold=0.35, coherence=_scorer()
    )
    ref_on = Syneidesis(
        strategy=_strategy(), top_k=3, publication_threshold=0.35, coherence=_scorer()
    )

    primary, counterfactual = await dual.select_dual(list(events), context=dict(ctx))
    ref_snap = await ref_on.select(list(events), context=dict(ctx))

    assert counterfactual is not None
    assert _ids(primary) == _ids(ref_snap)
    assert primary.salience_scores == ref_snap.salience_scores
    assert primary.inhibited == ref_snap.inhibited
    assert primary.metadata.get("coherence") == ref_snap.metadata.get("coherence")


@pytest.mark.asyncio
async def test_counterfactual_is_the_coherence_off_baseline():
    """The counterfactual arm equals a coherence-OFF select() over the same
    events — so the two arms differ by the layer alone."""
    events, ctx = _batch()
    dual = Syneidesis(
        strategy=_strategy(), top_k=3, publication_threshold=0.35, coherence=_scorer()
    )
    ref_off = Syneidesis(
        strategy=_strategy(), top_k=3, publication_threshold=0.35, coherence=None
    )

    _primary, counterfactual = await dual.select_dual(list(events), context=dict(ctx))
    ref_snap = await ref_off.select(list(events), context=dict(ctx))

    assert counterfactual is not None
    assert _ids(counterfactual) == _ids(ref_snap)
    assert counterfactual.salience_scores == ref_snap.salience_scores
    assert counterfactual.inhibited == ref_snap.inhibited
    # the coherence-off arm carries NO coherence metadata
    assert counterfactual.metadata.get("coherence") is None


@pytest.mark.asyncio
async def test_layer_off_yields_no_counterfactual():
    events, ctx = _batch()
    syn = Syneidesis(
        strategy=_strategy(), top_k=3, publication_threshold=0.35, coherence=None
    )
    ref = Syneidesis(
        strategy=_strategy(), top_k=3, publication_threshold=0.35, coherence=None
    )

    primary, counterfactual = await syn.select_dual(list(events), context=dict(ctx))
    ref_snap = await ref.select(list(events), context=dict(ctx))

    assert counterfactual is None  # nothing to ablate: the entity IS the baseline
    assert _ids(primary) == _ids(ref_snap)


@pytest.mark.asyncio
async def test_empty_events_gives_two_empty_inhibited_snapshots():
    syn = Syneidesis(
        strategy=_strategy(), top_k=3, publication_threshold=0.35, coherence=_scorer()
    )
    primary, counterfactual = await syn.select_dual(
        [], context={"tick_index": 4, "phases": {}}
    )
    assert counterfactual is not None
    assert primary.selected_events == [] and primary.inhibited
    assert counterfactual.selected_events == [] and counterfactual.inhibited


@pytest.mark.asyncio
async def test_phases_observed_exactly_once_per_dual_tick():
    """Observing twice would drift the coherence windows; assert one observe."""
    calls = {"n": 0}
    scorer = _scorer()
    real_observe = scorer.observe

    def counting_observe(phases):
        calls["n"] += 1
        return real_observe(phases)

    scorer.observe = counting_observe  # type: ignore[method-assign]
    syn = Syneidesis(
        strategy=_strategy(), top_k=3, publication_threshold=0.35, coherence=scorer
    )
    events, ctx = _batch()
    await syn.select_dual(list(events), context=dict(ctx))
    assert calls["n"] == 1


# --------------------------------------------------------------------------- #
# selection_delta — content-free numeric comparison
# --------------------------------------------------------------------------- #


def _snap(
    ids_scores: dict[str, float], selected: list[str], inhibited: bool
) -> WorkspaceSnapshot:
    selected_events = [
        (
            eid,
            Event(
                source="m",
                type="t",
                payload={},
                salience=0.0,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        for eid in selected
    ]
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=selected_events,
        inhibited=inhibited,
        salience_scores=ids_scores,
    )


def test_selection_delta_zero_when_identical():
    snap = _snap({"a": 0.9, "b": 0.4}, ["a", "b"], inhibited=False)
    d = selection_delta(snap, snap)
    assert d["selection_divergence_fraction"] == 0.0
    assert d["mean_ranking_divergence"] == 0.0
    assert d["inhibited_flip"] is False
    assert d["top_score_delta"] == 0.0


def test_selection_delta_flags_membership_and_inhibition_change():
    on = _snap({"a": 0.9, "b": 0.4, "c": 0.2}, ["a", "b"], inhibited=False)
    off = _snap({"a": 0.3, "b": 0.4, "c": 0.2}, ["b", "c"], inhibited=True)
    d = selection_delta(on, off)
    # union {a,b,c}, shared {b} -> divergence 2/3
    assert d["selection_divergence_fraction"] == pytest.approx(2 / 3)
    assert d["inhibited_on"] is False and d["inhibited_off"] is True
    assert d["inhibited_flip"] is True
    assert d["top_score_on"] == pytest.approx(0.9)
    assert d["top_score_off"] == pytest.approx(0.4)
    assert d["top_score_delta"] == pytest.approx(0.5)
    assert d["n_candidates"] == 3


# --------------------------------------------------------------------------- #
# Cycle integration — the recorder is driven, read-only, without changing behaviour
# --------------------------------------------------------------------------- #

from kaine.bus.client import AsyncBus, _decode_workspace  # noqa: E402
from kaine.bus.config import BusConfig  # noqa: E402
from kaine.bus.schema import WORKSPACE_STREAM, validate_event  # noqa: E402
from kaine.cycle import CognitiveCycle  # noqa: E402
from kaine.oscillator import FakeOscillator  # noqa: E402
from tests._fakes import FakeClock  # noqa: E402


class _PhaseModule:
    def __init__(self, name: str, oscillator: FakeOscillator) -> None:
        self.name = name
        self._osc = oscillator

    def phase(self) -> float:
        return self._osc.phase()


class _PhaseRegistry:
    def __init__(self, modules, streams) -> None:
        self._modules = list(modules)
        self._streams = list(streams)

    def active_streams(self):
        return list(self._streams)

    def all_modules(self):
        return list(self._modules)


async def _make_bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


async def _publish(bus: AsyncBus, source: str, eid: str, salience: float) -> None:
    ev = validate_event(
        source=source,
        type=f"{source}.out",
        payload={"id": eid},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(ev)


async def _last_broadcast(bus: AsyncBus) -> dict:
    entries = await bus._client.xrange(WORKSPACE_STREAM)  # type: ignore[attr-defined]
    assert entries, "expected a workspace broadcast"
    _, fields = entries[-1]
    return _decode_workspace(fields)


def _coherence_registry_and_syn():
    osc_soma, osc_chronos = FakeOscillator(), FakeOscillator()
    for _ in range(12):
        osc_soma.step(0.5)
        osc_chronos.step(0.5)
    registry = _PhaseRegistry(
        modules=[_PhaseModule("soma", osc_soma), _PhaseModule("chronos", osc_chronos)],
        streams=["soma.out", "chronos.out"],
    )
    syn = Syneidesis(
        strategy=_strategy(), top_k=5, publication_threshold=0.0, coherence=_scorer()
    )
    return registry, syn


@pytest.mark.asyncio
async def test_cycle_invokes_recorder_with_paired_snapshots():
    bus = await _make_bus()
    try:
        await _publish(bus, "soma", "a", 0.9)
        await _publish(bus, "chronos", "b", 0.8)
        registry, syn = _coherence_registry_and_syn()
        captured: list[tuple[WorkspaceSnapshot, WorkspaceSnapshot]] = []
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=syn,
            registry=registry,
            clock=FakeClock(),
            sleep=FakeClock().sleep,
            collect_phases=True,
            ablation_recorder=lambda on, off: captured.append((on, off)),
        )
        await cycle.tick()

        assert len(captured) == 1
        on, off = captured[0]
        assert isinstance(on, WorkspaceSnapshot) and isinstance(off, WorkspaceSnapshot)
        assert _ids(on)  # a non-empty coalition was selected
        # the primary reached the broadcast; the counterfactual carries no layer
        payload = await _last_broadcast(bus)
        assert off.metadata.get("coherence") is None
        assert on.metadata.get("coherence") == payload["metadata"].get("coherence")
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_recorder_does_not_change_the_broadcast():
    async def run(with_recorder: bool) -> dict:
        bus = await _make_bus()
        try:
            await _publish(bus, "soma", "a", 0.9)
            await _publish(bus, "chronos", "b", 0.8)
            registry, syn = _coherence_registry_and_syn()
            kw = {"ablation_recorder": (lambda on, off: None)} if with_recorder else {}
            cycle = CognitiveCycle(
                bus=bus,
                syneidesis=syn,
                registry=registry,
                clock=FakeClock(),
                sleep=FakeClock().sleep,
                collect_phases=True,
                **kw,
            )
            await cycle.tick()
            return await _last_broadcast(bus)
        finally:
            await bus.close()

    def _selection(payload: dict):
        # behaviour-relevant identity, excluding run-specific entry_id/timestamp
        return [
            (s["source"], s["type"], s["payload"].get("id"), s["salience"])
            for s in payload["selected"]
        ]

    with_rec = await run(True)
    without = await run(False)
    assert _selection(with_rec) == _selection(without)
    assert with_rec["metadata"].get("coherence") == without["metadata"].get("coherence")


@pytest.mark.asyncio
async def test_set_ablation_recorder_attaches_after_construction():
    """The composition-root seam: attach the recorder post-construction (the
    registry is built after the cycle) and it drives on the next experiential tick."""
    bus = await _make_bus()
    try:
        await _publish(bus, "soma", "a", 0.9)
        await _publish(bus, "chronos", "b", 0.8)
        registry, syn = _coherence_registry_and_syn()
        captured: list[tuple[WorkspaceSnapshot, WorkspaceSnapshot]] = []
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=syn,
            registry=registry,
            clock=FakeClock(),
            sleep=FakeClock().sleep,
            collect_phases=True,
        )
        cycle.set_ablation_recorder(lambda on, off: captured.append((on, off)))
        await cycle.tick()
        assert len(captured) == 1
    finally:
        await bus.close()


# --------------------------------------------------------------------------- #
# AblationObserver — computes the delta and enqueues it, content-free
# --------------------------------------------------------------------------- #


def test_ablation_observer_enqueues_the_delta():
    from kaine.evaluation.observers.ablation_observer import AblationObserver

    captured: list[dict] = []

    class _FakeSink:
        def enqueue(self, entry: dict) -> None:
            captured.append(entry)

    obs = AblationObserver(_FakeSink())
    on = _snap({"a": 0.9, "b": 0.4}, ["a"], inhibited=False)
    off = _snap({"a": 0.3, "b": 0.4}, ["b"], inhibited=True)
    obs.record(on, off)

    assert len(captured) == 1
    rec = captured[0]
    assert rec["selection_divergence_fraction"] == pytest.approx(
        1.0
    )  # disjoint selections
    assert rec["inhibited_flip"] is True
    assert "ts" in rec and rec["tick_index"] == 0
    # content-free: only the declared numeric/categorical keys, no event payloads
    assert "payload" not in rec and "selected_events" not in rec
