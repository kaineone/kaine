# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Memory pruning counts in the sleep summary.

When associative replay is enabled, phase 3 performs the actual prune and
its counts must overwrite the deferred phase 2 counts. When associative replay
is disabled, the phase 2 downscale counts are used and prune is never called.
"""


import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class RecordingAffect:
    def __init__(self) -> None:
        self.resets = 0

    async def affective_reset(self) -> None:
        self.resets += 1


class ConfigurableEpisodicMemory:
    def __init__(self, prune_result: dict | None = None) -> None:
        self.prune_result = prune_result or {}
        self.prune_called = False

    async def consolidate_now(self) -> int:
        return 0

    def open_replay_window(self) -> None:
        pass

    def close_replay_window(self) -> None:
        pass

    async def replay_now(self) -> list:
        return []

    async def downscale(self, protect=(), *, prune=True):
        result = {
            "n_new": 0,
            "factor": 1.0,
            "protected": 0,
            "total_before": 0.0,
            "total_after": 0.0,
            "pruned_floor": 0,
            "pruned_budget": 0,
            "store_bytes": 100,
            "blocked": None,
            "blocked_sleeps": 0,
            "persist_refusals": 0,
        }
        if not prune:
            result["prune_deferred"] = True
        return result

    async def associate(self) -> dict:
        return {"pairs": []}

    async def prune(self) -> dict:
        self.prune_called = True
        return self.prune_result


def _make_sleep(bus, tmp_path, *, episodic_memory, affect, associative=False):
    return Sleep(
        bus,
        episodic_memory=episodic_memory,
        affect=affect,
        trainer=FakeTrainer(),
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=tmp_path / "intent.jsonl",
            adapter_output_dir=tmp_path / "adapters",
            enabled=False,
        ),
        perception_desired_path=tmp_path / "perception_desired.json",
        associative_replay_enabled=associative,
    )


@pytest.mark.asyncio
async def test_associative_replay_uses_phase3_prune_counts(bus, tmp_path):
    episodic_memory = ConfigurableEpisodicMemory(
        prune_result={
            "pruned_floor": 2,
            "pruned_budget": 1,
            "links_pruned": 3,
            "nodes_pruned": 1,
            "store_bytes": 50,
        }
    )
    affect = RecordingAffect()
    sleep = _make_sleep(
        bus,
        tmp_path,
        episodic_memory=episodic_memory,
        affect=affect,
        associative=True,
    )

    summary = await sleep.enter_sleep()

    assert summary["memory_pruned_floor"] == 2
    assert summary["memory_pruned_budget"] == 1
    assert summary["memory_store_bytes"] == 50
    assert summary["memory_links_pruned"] == 3
    assert summary["memory_nodes_pruned"] == 1
    assert episodic_memory.prune_called is True


@pytest.mark.asyncio
async def test_associative_replay_skipped_prune_uses_phase2_counts(bus, tmp_path):
    episodic_memory = ConfigurableEpisodicMemory(
        prune_result={"skipped": "no downscaling awaits pruning"}
    )
    affect = RecordingAffect()
    sleep = _make_sleep(
        bus,
        tmp_path,
        episodic_memory=episodic_memory,
        affect=affect,
        associative=True,
    )

    summary = await sleep.enter_sleep()

    assert summary["memory_pruned_floor"] == 0
    assert summary["memory_pruned_budget"] == 0
    assert summary["memory_store_bytes"] == 100
    assert "memory_links_pruned" not in summary
    assert "memory_nodes_pruned" not in summary
    assert episodic_memory.prune_called is True


@pytest.mark.asyncio
async def test_no_associative_replay_uses_phase2_counts_and_skips_prune(
    bus, tmp_path
):
    episodic_memory = ConfigurableEpisodicMemory(
        prune_result={
            "pruned_floor": 2,
            "pruned_budget": 1,
            "links_pruned": 3,
            "nodes_pruned": 1,
            "store_bytes": 50,
        }
    )
    affect = RecordingAffect()
    sleep = _make_sleep(
        bus,
        tmp_path,
        episodic_memory=episodic_memory,
        affect=affect,
        associative=False,
    )

    summary = await sleep.enter_sleep()

    assert summary["memory_pruned_floor"] == 0
    assert summary["memory_pruned_budget"] == 0
    assert summary["memory_store_bytes"] == 100
    assert "memory_links_pruned" not in summary
    assert "memory_nodes_pruned" not in summary
    assert episodic_memory.prune_called is False
