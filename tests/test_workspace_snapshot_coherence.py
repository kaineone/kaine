# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""WorkspaceSnapshot.metadata['coherence'] flow (oscillatory-layer).

Proves that when the layer is ENABLED the computed coalition PLV is written to
`snapshot.metadata['coherence']` and reaches the `workspace.broadcast` payload
(the key the sidecar coherence_observer consumes), and that it is ABSENT when
the layer is disabled. Uses FakeOscillator (no snnTorch dependency).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import _decode_workspace
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import WORKSPACE_STREAM, validate_event
from kaine.cycle import CognitiveCycle
from kaine.oscillator import FakeOscillator
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)
from kaine.workspace.coherence import CoherenceScorer
from tests._fakes import FakeClock


class _PhaseModule:
    """Minimal module exposing name + phase() for the cycle's phase collector."""

    def __init__(self, name: str, oscillator: FakeOscillator) -> None:
        self.name = name
        self._osc = oscillator

    def phase(self) -> float:
        return self._osc.phase()


class _PhaseRegistry:
    def __init__(self, modules: list[_PhaseModule], streams: list[str]) -> None:
        self._modules = list(modules)
        self._streams = list(streams)

    def active_streams(self) -> list[str]:
        return list(self._streams)

    def all_modules(self):
        return list(self._modules)


def _strategy() -> RuleBasedSalience:
    return RuleBasedSalience(
        novelty=NoveltyTracker(window=64),
        goal_scorer=StaticGoalScorer(),
        thymos_modulator=StaticThymosModulator(),
    )


async def _make_bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


async def _last_broadcast(bus: AsyncBus) -> dict:
    """Decode the most recent workspace.broadcast snapshot payload."""
    entries = await bus._client.xrange(WORKSPACE_STREAM)  # type: ignore[attr-defined]
    assert entries, "expected a workspace broadcast"
    _, fields = entries[-1]
    return _decode_workspace(fields)


async def _publish(bus: AsyncBus, source: str, eid: str, salience: float) -> None:
    ev = validate_event(
        source=source,
        type=f"{source}.out",
        payload={"id": eid},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(ev)


@pytest.mark.asyncio
async def test_coherence_metadata_present_when_enabled():
    bus = await _make_bus()
    try:
        await _publish(bus, "soma", "a", 0.9)
        await _publish(bus, "chronos", "b", 0.8)

        # Advance fake oscillators so phases differ between the two modules.
        osc_soma = FakeOscillator()
        osc_chronos = FakeOscillator(phase_step=0.9)
        for _ in range(12):
            osc_soma.step(0.5)
            osc_chronos.step(0.5)

        registry = _PhaseRegistry(
            modules=[
                _PhaseModule("soma", osc_soma),
                _PhaseModule("chronos", osc_chronos),
            ],
            streams=["soma.out", "chronos.out"],
        )
        scorer = CoherenceScorer(
            plv_window=10, coherence_floor=0.8, coherence_ceiling=1.25
        )
        syn = Syneidesis(
            strategy=_strategy(),
            top_k=5,
            publication_threshold=0.0,
            coherence=scorer,
        )
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=syn,
            registry=registry,
            clock=FakeClock(),
            sleep=FakeClock().sleep,
            collect_phases=True,
        )
        await cycle.tick()

        payload = await _last_broadcast(bus)
        assert "coherence" in payload["metadata"]
        assert payload["metadata"]["coherence"] is not None
        assert 0.0 <= float(payload["metadata"]["coherence"]) <= 1.0
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_coherence_metadata_absent_when_disabled():
    bus = await _make_bus()
    try:
        await _publish(bus, "soma", "a", 0.9)
        registry = _PhaseRegistry(
            modules=[_PhaseModule("soma", FakeOscillator())],
            streams=["soma.out"],
        )
        syn = Syneidesis(
            strategy=_strategy(), top_k=5, publication_threshold=0.0
        )  # coherence=None ⇒ disabled
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=syn,
            registry=registry,
            clock=FakeClock(),
            sleep=FakeClock().sleep,
            collect_phases=False,
        )
        await cycle.tick()

        payload = await _last_broadcast(bus)
        assert payload["metadata"].get("coherence") is None
    finally:
        await bus.close()
