# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Integration tests for the Hypnos/Phantasia scenario window path.

These run a real Hypnos sleep against real Mnemos and Phantasia instances on
the bus so the explicit open/close window path is exercised like a running
system.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.hypnos import FakeTrainer, Hypnos, VoiceAlignmentConfig
from kaine.modules.mnemos import FakeEmbedder, InMemoryStorage, Mnemos, MnemosCore
from kaine.modules.phantasia.module import Phantasia


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(source: str, type_: str, payload=None, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events, *, inhibited: bool = False, tick: int = 1) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[(f"{i}-0", ev) for i, ev in enumerate(events)],
        inhibited=inhibited,
    )


async def _new_mnemos(bus: AsyncBus, *, capacity: int = 8, **kwargs) -> Mnemos:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = MnemosCore(embedder=emb, storage=storage, short_term_capacity=capacity)
    return Mnemos(bus, core=core, **kwargs)


class FakeThymos:
    """Stand-in thymos that only counts affective resets."""

    def __init__(self) -> None:
        self.resets = 0

    async def affective_reset(self) -> None:
        self.resets += 1


def _make_hypnos(
    bus: AsyncBus,
    tmp_path: Path,
    mnemos: Mnemos,
    thymos: FakeThymos,
    *,
    phantasia=None,
    associative_replay_enabled: bool = False,
) -> Hypnos:
    return Hypnos(
        bus,
        mnemos=mnemos,
        thymos=thymos,
        trainer=FakeTrainer(),
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=tmp_path / "intent.jsonl",
            adapter_output_dir=tmp_path / "adapters",
            enabled=False,
        ),
        perception_desired_path=tmp_path / "perception_desired.json",
        phantasia=phantasia,
        associative_replay_enabled=associative_replay_enabled,
    )


class RecordingMnemos:
    """Mnemos fake that records call order for phase sequencing tests."""

    def __init__(
        self,
        calls: list[str],
        hang_in: str | None = None,
    ) -> None:
        self.calls = calls
        self.hang_in = hang_in
        self.entered = asyncio.Event()

    async def consolidate_now(self) -> int:
        self.calls.append("consolidate")
        if self.hang_in == "consolidate":
            self.entered.set()
            await asyncio.Event().wait()
        return 0

    def open_replay_window(self) -> None:
        self.calls.append("open")

    def close_replay_window(self) -> None:
        self.calls.append("close")

    async def replay_now(self) -> list:
        self.calls.append("replay")
        if self.hang_in == "replay":
            self.entered.set()
            await asyncio.Event().wait()
        return []

    def downscale_activations(self, factor: float) -> int:
        self.calls.append("downscale")
        return 0

    async def select_cross_period_traces(
        self,
        *,
        periods: int,
        per_period: int,
    ) -> dict:
        self.calls.append("associative")
        return {"episodic": [{"point_id": "p1", "text": "t"}]}


class RecordingPhantasia:
    """Phantasia fake that records window calls and scenario generation."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def open_scenario_window(self) -> None:
        self.calls.append("ph_open")

    def close_scenario_window(self) -> None:
        self.calls.append("ph_close")

    async def generate_scenario(self, *, seed_memory_id: str = "") -> list:
        self.calls.append("scenario")
        return []


async def test_sleep_cues_phantasia_through_the_bus(bus: AsyncBus, tmp_path: Path):
    """A real sleep produces a phantasia.scenario for every mnemos.replay cue."""
    mnemos = await _new_mnemos(bus, replay_selection_top_k=5, replay_redact_content=False)
    phantasia = Phantasia(bus, backend="fake", rollout_horizon=4)
    hypnos = _make_hypnos(bus, tmp_path, mnemos, FakeThymos(), phantasia=phantasia)

    await mnemos.initialize()
    await phantasia.initialize()
    try:
        for i in range(4):
            await phantasia.on_workspace(
                _snapshot([_event("soma", "soma.report", salience=0.4)], tick=i)
            )

        for i in range(3):
            await mnemos.core.store(
                f"trace {i}",
                payload={"idx": i},
                affect={
                    "intensity": 0.2 * (i + 1),
                    "valence": 0.0,
                    "dominance": 0.0,
                },
                collection="short_term",
            )

        summary = await hypnos.enter_sleep()

        replayed = {
            ev.payload["memory_id"]
            for _, ev in await bus.read("mnemos.out", last_id="0")
            if ev.type == "mnemos.replay"
        }
        assert len(replayed) == 3

        deadline = asyncio.get_running_loop().time() + 3
        seed_ids = set()
        while seed_ids != replayed and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.02)
            events = await bus.read("phantasia.out", last_id="0")
            seed_ids = {
                ev.payload["seed_memory_id"]
                for _, ev in events
                if ev.type == "phantasia.scenario"
            }
        assert seed_ids == replayed, f"expected scenarios for {replayed}, got {seed_ids}"

        assert phantasia.window_active is False
        assert summary["alert"] is False
    finally:
        await phantasia.shutdown()
        await mnemos.shutdown()


async def test_window_is_open_during_phases_two_and_three(bus: AsyncBus, tmp_path: Path):
    """Phantasia's window wraps deep consolidation and associative replay."""
    calls: list = []
    mnemos = RecordingMnemos(calls)
    phantasia = RecordingPhantasia(calls)
    hypnos = _make_hypnos(
        bus,
        tmp_path,
        mnemos,
        FakeThymos(),
        phantasia=phantasia,
        associative_replay_enabled=True,
    )

    await hypnos.enter_sleep()
    assert calls == [
        "consolidate",
        "ph_open",
        "open",
        "replay",
        "close",
        "downscale",
        "associative",
        "scenario",
        "ph_close",
    ]


async def test_cancel_in_phase_two_closes_the_window(bus: AsyncBus, tmp_path: Path):
    """Cancellation during phase 2 still runs the Phantasia window cleanup."""
    calls: list = []
    mnemos = RecordingMnemos(calls, hang_in="replay")
    phantasia = RecordingPhantasia(calls)
    hypnos = _make_hypnos(
        bus,
        tmp_path,
        mnemos,
        FakeThymos(),
        phantasia=phantasia,
        associative_replay_enabled=True,
    )

    task = asyncio.create_task(hypnos.enter_sleep())
    await asyncio.wait_for(mnemos.entered.wait(), 5)
    task.cancel()
    (outcome,) = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(outcome, asyncio.CancelledError)

    assert "ph_open" in calls
    assert "ph_close" in calls
    assert calls.index("ph_close") > calls.index("ph_open")


async def test_phantasia_without_window_methods_is_still_cued(bus: AsyncBus, tmp_path: Path):
    """A Phantasia collaborator that only implements generate_scenario still works."""
    class CueOnlyPhantasia:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def generate_scenario(self, *, seed_memory_id: str = "") -> list:
            self.calls.append(seed_memory_id)
            return []

    phantasia = CueOnlyPhantasia()
    mnemos = RecordingMnemos([])
    hypnos = _make_hypnos(
        bus,
        tmp_path,
        mnemos,
        FakeThymos(),
        phantasia=phantasia,
        associative_replay_enabled=True,
    )

    summary = await hypnos.enter_sleep()
    assert len(phantasia.calls) == 1
    phase = next(p for p in summary["phases"] if p.get("phase") == "associative_replay")
    assert phase["success"] is True
