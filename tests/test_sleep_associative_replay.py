# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit and pipeline tests for sleep phase 3 associative replay.

The associative_replay phase co-replays related trace pairs as weighted links,
records each pair as a weighted association, then prunes. It does not cue the
world model module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig
from kaine.modules.sleep.phases import associative_replay


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


class FakeEpisodicMemory:
    def __init__(
        self,
        *,
        pairs: list[dict[str, Any]] | None = None,
        associate_raise: Exception | None = None,
        prune_raise: Exception | None = None,
        prune_summary: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[str | tuple[str, Any]] = []
        self.pairs = pairs or []
        self.associate_raise = associate_raise
        self.prune_raise = prune_raise
        self.prune_summary = prune_summary if prune_summary is not None else {"pruned": 0}

    async def consolidate_now(self) -> int:
        self.calls.append("consolidate")
        return 0

    def open_replay_window(self) -> None:
        self.calls.append("open")

    def close_replay_window(self) -> None:
        self.calls.append("close")

    async def replay_now(self) -> list:
        self.calls.append("replay")
        return []

    async def downscale(self, protect=(), *, prune=True):
        self.calls.append(("downscale", {"protect": protect, "prune": prune}))
        return {"factor": 1.0}

    async def associate(self) -> dict[str, Any]:
        self.calls.append("associate")
        if self.associate_raise is not None:
            raise self.associate_raise
        summary: dict[str, Any] = {"links": 2, "nodes": 3}
        if self.pairs:
            summary["pairs"] = list(self.pairs)
        return summary

    async def prune(self) -> dict[str, Any]:
        self.calls.append("prune")
        if self.prune_raise is not None:
            raise self.prune_raise
        return dict(self.prune_summary)


class FlagOffEpisodicMemory:
    def __init__(self, calls: list[str | tuple[str, Any]]) -> None:
        self.calls = calls
        self.downscale_kwargs: dict[str, Any] | None = None

    async def consolidate_now(self) -> int:
        self.calls.append("consolidate")
        return 0

    def open_replay_window(self) -> None:
        self.calls.append("open")

    def close_replay_window(self) -> None:
        self.calls.append("close")

    async def replay_now(self) -> list:
        self.calls.append("replay")
        return []

    async def downscale(self, protect=()):
        self.calls.append("downscale")
        self.downscale_kwargs = {"protect": protect}
        return {"factor": 1.0}

    async def associate(self) -> dict[str, Any]:
        self.calls.append("associate")
        return {"pairs": []}

    async def prune(self) -> dict[str, Any]:
        self.calls.append("prune")
        return {"pruned": 0}


def _make_sleep(
    bus: AsyncBus,
    tmp_path: Path,
    episodic_memory: Any,
    *,
    associative_replay_enabled: bool = False,
) -> Sleep:
    return Sleep(
        bus,
        episodic_memory=episodic_memory,
        affect=RecordingAffect(),
        trainer=FakeTrainer(),
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=tmp_path / "intent.jsonl",
            adapter_output_dir=tmp_path / "adapters",
            enabled=False,
        ),
        perception_desired_path=tmp_path / "perception_desired.json",
        associative_replay_enabled=associative_replay_enabled,
    )


async def test_disabled_is_successful_noop():
    fake = FakeEpisodicMemory(pairs=[{"a": "p1", "b": "p2", "weight": 1.0}])
    result = await associative_replay(
        enabled=False, episodic_memory=fake, publish=lambda p: None
    )
    assert result.success is True
    assert result.phase == "associative_replay"
    assert (
        result.metadata["skipped"] == "associative_replay feature flag not enabled"
    )
    assert fake.calls == []


async def test_enabled_without_episodic_memory_skips():
    result = await associative_replay(enabled=True, episodic_memory=None)
    assert result.success is True
    assert result.metadata["skipped"] == "no Episodic memory available"


async def test_enabled_calls_associate_then_prune_and_publishes_pairs():
    pairs = [
        {"a": "p1", "b": "p2", "weight": 0.75},
        {"a": "p3", "b": "p4", "weight": 0.25},
    ]
    fake = FakeEpisodicMemory(pairs=pairs, prune_summary={"dropped": 1})
    published: list[dict[str, Any]] = []

    def publish(payload: dict[str, Any]) -> None:
        published.append(payload)

    result = await associative_replay(
        enabled=True, episodic_memory=fake, publish=publish
    )
    assert result.success is True
    assert fake.calls == ["associate", "prune"]
    assert len(published) == 2
    for pub, pair in zip(published, pairs):
        assert set(pub.keys()) == {"a", "b", "weight"}
        assert pub["a"] == pair["a"]
        assert pub["b"] == pair["b"]
        assert pub["weight"] == pair["weight"]
    assert result.metadata["pairs"] == 2
    assert result.metadata["associations_published"] == 2
    assert result.metadata["prune"] == {"dropped": 1}
    assert "pairs" not in result.metadata["associate"]
    assert result.metadata["associate"]["links"] == 2


async def test_extra_pair_keys_do_not_leak_into_published_payload():
    fake = FakeEpisodicMemory(
        pairs=[{"a": "p1", "b": "p2", "weight": 0.5, "text": "secret"}]
    )
    published: list[dict[str, Any]] = []

    def publish(payload: dict[str, Any]) -> None:
        published.append(payload)

    result = await associative_replay(
        enabled=True, episodic_memory=fake, publish=publish
    )
    assert result.success is True
    assert published == [{"a": "p1", "b": "p2", "weight": 0.5}]
    assert "text" not in published[0]


async def test_associate_failure_still_prunes_and_reports_error():
    fake = FakeEpisodicMemory(associate_raise=RuntimeError("associate boom"))
    result = await associative_replay(enabled=True, episodic_memory=fake)
    assert result.success is False
    assert result.error is not None
    assert "associate" in result.error
    assert "RuntimeError" in result.error
    assert fake.calls == ["associate", "prune"]
    assert result.metadata.get("pairs", 0) == 0


async def test_prune_failure_still_publishes_pairs():
    pairs = [{"a": "p1", "b": "p2", "weight": 0.8}]
    fake = FakeEpisodicMemory(pairs=pairs, prune_raise=RuntimeError("prune boom"))
    published: list[dict[str, Any]] = []

    async def publish(payload: dict[str, Any]) -> None:
        published.append(payload)

    result = await associative_replay(
        enabled=True, episodic_memory=fake, publish=publish
    )
    assert result.success is False
    assert result.error is not None
    assert "prune" in result.error
    assert "RuntimeError" in result.error
    assert len(published) == 1
    assert result.metadata["associations_published"] == 1


async def test_async_publish_is_awaited():
    fake = FakeEpisodicMemory(pairs=[{"a": "p1", "b": "p2", "weight": 0.1}])
    calls: list[dict[str, Any]] = []

    async def publish(payload: dict[str, Any]) -> None:
        calls.append(payload)

    result = await associative_replay(
        enabled=True, episodic_memory=fake, publish=publish
    )
    assert result.success is True
    assert len(calls) == 1
    assert calls[0] == {"a": "p1", "b": "p2", "weight": 0.1}


async def test_publish_failure_is_recorded_and_continues():
    fake = FakeEpisodicMemory(
        pairs=[
            {"a": "p1", "b": "p2", "weight": 0.1},
            {"a": "p3", "b": "p4", "weight": 0.2},
        ]
    )
    calls: list[dict[str, Any]] = []

    def publish(payload: dict[str, Any]) -> None:
        if len(calls) == 0:
            calls.append(payload)
            raise ValueError("first fails")
        calls.append(payload)

    result = await associative_replay(
        enabled=True, episodic_memory=fake, publish=publish
    )
    assert result.success is False
    assert result.error is not None
    assert result.error.startswith("publish")
    assert "ValueError" in result.error
    assert len(calls) == 2
    assert result.metadata["associations_published"] == 1


async def test_skipped_associate_publishes_nothing_and_succeeds():
    class SkipEpisodicMemory:
        async def associate(self) -> dict[str, Any]:
            return {"skipped": "waiting for next sleep"}

        async def prune(self) -> dict[str, Any]:
            return {"pruned": 0}

    def publish(payload: dict[str, Any]) -> None:
        raise AssertionError("publish should not be called")

    result = await associative_replay(
        enabled=True, episodic_memory=SkipEpisodicMemory(), publish=publish
    )
    assert result.success is True
    assert result.metadata.get("pairs", -1) == 0
    assert result.metadata.get("associations_published", -1) == 0


async def test_pipeline_flag_off_does_not_run_phase_three(bus, tmp_path):
    calls: list[str | tuple[str, Any]] = []
    episodic = FlagOffEpisodicMemory(calls)
    sleep = _make_sleep(
        bus, tmp_path, episodic, associative_replay_enabled=False
    )

    summary = await sleep.enter_sleep()

    assert [c for c in calls if isinstance(c, str)] == [
        "consolidate",
        "open",
        "replay",
        "close",
        "downscale",
    ]
    assert episodic.downscale_kwargs == {"protect": []}
    assert "associate" not in [c for c in calls if isinstance(c, str)]
    assert "prune" not in [c for c in calls if isinstance(c, str)]
    phase = next(
        p for p in summary["phases"] if p.get("phase") == "associative_replay"
    )
    assert phase["success"] is True
    assert (
        phase["metadata"]["skipped"]
        == "associative_replay feature flag not enabled"
    )


async def test_pipeline_flag_on_runs_phase_three_and_publishes_event(bus, tmp_path):
    pairs = [{"a": "m1", "b": "m2", "weight": 0.9}]
    episodic = FakeEpisodicMemory(pairs=pairs)
    sleep = _make_sleep(
        bus, tmp_path, episodic, associative_replay_enabled=True
    )

    summary = await sleep.enter_sleep()

    downscale_calls = [
        c for c in episodic.calls if isinstance(c, tuple) and c[0] == "downscale"
    ]
    assert downscale_calls == [
        ("downscale", {"protect": [], "prune": False})
    ]
    string_calls = [c for c in episodic.calls if isinstance(c, str)]
    assert string_calls == ["consolidate", "open", "replay", "close", "associate", "prune"]

    entries = await bus.read("sleep.out", last_id="0")
    assoc_events = [e for _, e in entries if e.type == "sleep.association"]
    assert len(assoc_events) == 1
    assert assoc_events[0].payload == {"a": "m1", "b": "m2", "weight": 0.9}

    phase = next(
        p for p in summary["phases"] if p.get("phase") == "associative_replay"
    )
    assert phase["success"] is True
    assert phase["metadata"]["pairs"] == 1
    assert phase["metadata"]["associations_published"] == 1
