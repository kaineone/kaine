# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.sleep.phases import (
    affective_reset,
    associative_replay,
    consolidate_memory,
    deep_consolidation,
    light_consolidation,
    recalibrate_time,
    reset_affect,
)


class FakeEpisodicMemory:
    def __init__(self, moved: int = 7) -> None:
        self.moved = moved
        self.called = 0

    async def consolidate_now(self) -> int:
        self.called += 1
        return self.moved


class FakeAffect:
    def __init__(self) -> None:
        self.reset_calls = 0

    async def affective_reset(self) -> None:
        self.reset_calls += 1



class FakeResetter:
    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        self.calls += 1


@pytest.mark.asyncio
async def test_consolidate_memory_success():
    m = FakeEpisodicMemory(moved=4)
    r = await consolidate_memory(m)
    assert r.success is True
    assert r.phase == "memory_consolidation"
    assert r.metadata["entries_consolidated"] == 4


@pytest.mark.asyncio
async def test_consolidate_memory_no_episodic_memory():
    r = await consolidate_memory(None)
    assert r.success is True
    assert "skipped" in r.metadata


@pytest.mark.asyncio
async def test_consolidate_memory_error():
    class BoomEpisodicMemory:
        async def consolidate_now(self):
            raise RuntimeError("boom")

    r = await consolidate_memory(BoomEpisodicMemory())
    assert r.success is False
    assert "RuntimeError" in (r.error or "")



@pytest.mark.asyncio
async def test_reset_affect_calls_reset():
    t = FakeAffect()
    r = await reset_affect(t)
    assert r.success is True
    assert t.reset_calls == 1


@pytest.mark.asyncio
async def test_reset_affect_no_affect():
    r = await reset_affect(None)
    assert r.success is True


@pytest.mark.asyncio
async def test_recalibrate_time_resets_all():
    rs = [FakeResetter(), FakeResetter()]
    r = await recalibrate_time(rs)
    assert r.success is True
    for x in rs:
        assert x.calls == 1
    assert r.metadata["reset_count"] == 2


@pytest.mark.asyncio
async def test_recalibrate_time_empty_list_skipped():
    r = await recalibrate_time([])
    assert r.success is True
    assert "skipped" in r.metadata


@pytest.mark.asyncio
async def test_recalibrate_time_partial_failure():
    class Bad:
        def reset(self):
            raise RuntimeError("nope")

    rs = [FakeResetter(), Bad(), FakeResetter()]
    r = await recalibrate_time(rs)
    assert r.success is False
    assert "RuntimeError" in (r.error or "")
    # Both good resetters were still called.
    assert rs[0].calls == 1
    assert rs[2].calls == 1


# ===========================================================================
# New five-phase tests (hypnos-fatigue-phases restructure)
# ===========================================================================

# --- Phase 1: light_consolidation ---

class FakeFullEpisodicMemory:
    """Full-protocol episodic memory module fake for new-phase tests."""

    def __init__(self, moved: int = 3) -> None:
        self.moved = moved
        self.consolidate_calls = 0
        self.downscale_calls: list[float] = []
        self.replay_calls = 0

    async def consolidate_now(self) -> int:
        self.consolidate_calls += 1
        return self.moved

    async def downscale(self, protect=()):
        protect = list(protect)
        self.downscale_calls.append(protect)
        return {"n_new": 0, "factor": 1.0, "protected": len(protect), "total_before": 0.0, "total_after": 0.0, "silent": 0}

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []  # empty replay (window guard not needed in unit test)


class FakeModule:
    """Stand-in BaseModule for oscillator hook testing."""

    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.set_frequency_calls: list[float] = []

    def set_frequency(self, scale: float) -> None:
        self.set_frequency_calls.append(scale)


@pytest.mark.asyncio
async def test_light_consolidation_calls_consolidate_and_oscillator():
    m = FakeFullEpisodicMemory(moved=4)
    mod_a = FakeModule("a")
    mod_b = FakeModule("b")
    r = await light_consolidation(m, active_modules=[mod_a, mod_b], frequency_scale=0.5)
    assert r.phase == "light_consolidation"
    assert r.success is True
    assert r.metadata["entries_consolidated"] == 4
    assert r.metadata["modules_frequency_called"] == 2
    # Both modules had set_frequency called with the right scale
    assert mod_a.set_frequency_calls == [0.5]
    assert mod_b.set_frequency_calls == [0.5]


@pytest.mark.asyncio
async def test_light_consolidation_no_episodic_memory():
    r = await light_consolidation(None)
    assert r.success is True
    assert "consolidation_skipped" in r.metadata


@pytest.mark.asyncio
async def test_light_consolidation_empty_module_list():
    m = FakeFullEpisodicMemory()
    r = await light_consolidation(m, active_modules=[], frequency_scale=0.5)
    assert r.success is True
    assert r.metadata["modules_frequency_called"] == 0


# --- Phase 2: deep_consolidation ---

@pytest.mark.asyncio
async def test_deep_consolidation_calls_downscale_and_replay():
    m = FakeFullEpisodicMemory()
    r = await deep_consolidation(m, replay_window_s=1.0)
    assert r.phase == "deep_consolidation"
    assert r.success is True
    assert len(m.downscale_calls) == 1
    assert m.replay_calls == 1
    assert r.metadata["downscale"] == {
        "n_new": 0,
        "factor": 1.0,
        "protected": 0,
        "total_before": 0.0,
        "total_after": 0.0,
        "silent": 0,
    }


@pytest.mark.asyncio
async def test_deep_consolidation_suspends_and_restores_perception():
    """suspend_perception is called before replay; restore_perception after."""
    m = FakeFullEpisodicMemory()
    calls: list[str] = []

    def suspend():
        calls.append("suspend")

    def restore():
        calls.append("restore")

    await deep_consolidation(
        m,
        suspend_perception=suspend,
        restore_perception=restore,
    )
    assert calls == ["suspend", "restore"], (
        "perception must be suspended then restored in order"
    )


@pytest.mark.asyncio
async def test_deep_consolidation_restores_even_on_replay_error():
    """restore_perception is called even when replay_now raises; no downscale."""
    class ReplayBoom(FakeFullEpisodicMemory):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[str] = []

        async def replay_now(self) -> list:
            self.calls.append("replay")
            raise RuntimeError("replay boom")

        async def downscale(self, protect=()):
            self.calls.append("downscale")
            return {"n_new": 0, "factor": 1.0, "protected": 0, "total_before": 0.0, "total_after": 0.0, "pruned_floor": 0, "pruned_budget": 0, "store_bytes": 0}

    m = ReplayBoom()
    calls: list[str] = []

    def suspend():
        calls.append("suspend")

    def restore():
        calls.append("restore")

    r = await deep_consolidation(
        m,
        suspend_perception=suspend,
        restore_perception=restore,
    )
    # Replay error is captured; restore still ran and downscale was skipped.
    assert "restore" in calls
    assert "replay" in m.calls
    assert "downscale" not in m.calls
    assert r.metadata["downscale_skipped"] == "replay failed"
    assert r.success is False  # error reported


@pytest.mark.asyncio
async def test_deep_consolidation_replays_inside_its_window_then_downscales():
    """The replay window opens, replays, closes, and only then activations downscale."""
    class OrderedEpisodicMemory(FakeFullEpisodicMemory):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[str] = []

        def open_replay_window(self) -> None:
            self.calls.append("open")

        def close_replay_window(self) -> None:
            self.calls.append("close")

        async def replay_now(self) -> list:
            self.calls.append("replay")
            return []

        async def downscale(self, protect=()):
            self.calls.append("downscale")
            return {"n_new": 0, "factor": 1.0, "protected": len(protect), "total_before": 0.0, "total_after": 0.0, "silent": 0}

    m = OrderedEpisodicMemory()
    r = await deep_consolidation(m)
    assert r.success is True
    assert m.calls == ["open", "replay", "close", "downscale"]


@pytest.mark.asyncio
async def test_deep_consolidation_closes_its_window_when_replay_raises():
    """A replay error still closes the window before reporting failure."""
    class ReplayBoomOrdered(FakeFullEpisodicMemory):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[str] = []

        def open_replay_window(self) -> None:
            self.calls.append("open")

        def close_replay_window(self) -> None:
            self.calls.append("close")

        async def replay_now(self) -> list:
            self.calls.append("replay")
            raise RuntimeError("replay boom")

    m = ReplayBoomOrdered()
    r = await deep_consolidation(m)
    assert r.success is False
    assert "close" in m.calls
    assert m.calls.index("close") > m.calls.index("replay")
    assert "downscale" not in m.calls
    assert r.metadata["downscale_skipped"] == "replay failed"


@pytest.mark.asyncio
async def test_deep_consolidation_no_episodic_memory():
    r = await deep_consolidation(None)
    assert r.success is True
    assert "skipped" in r.metadata


# --- Phase 2: downscaling preserves relative ordering ---

@pytest.mark.asyncio
async def test_downscaling_preserves_vectors_and_reports_factor():
    """EpisodicMemory.downscale() downscales trace strengths, not vectors, and reports the factor."""
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    bus = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.FakeRedis(decode_responses=True),
    )
    core = EpisodicMemoryCore(
        embedder=FakeEmbedder(),
        storage=InMemoryStorage(latent_dim=32),
        traces_per_day=2.0,
    )
    episodic_memory = EpisodicMemory(bus, core=core)
    await core.initialize()
    await core.store("first episodic trace", collection="episodic")
    await core.store("second episodic trace", collection="episodic")

    names = core.persisted_collection_names()
    before = await core.storage.export(names)
    summary = await episodic_memory.downscale()
    after = await core.storage.export(names)

    for collection, before_pts in before.items():
        for before_pt, after_pt in zip(before_pts, after[collection]):
            assert before_pt["vector"] == after_pt["vector"]

    assert summary["n_new"] == 2
    assert summary["factor"] == pytest.approx(0.82, rel=1e-12)

    await bus.close()


# --- Phase 3: associative_replay stub ---

@pytest.mark.asyncio
async def test_associative_replay_stub_disabled():
    r = await associative_replay(enabled=False)
    assert r.phase == "associative_replay"
    assert r.success is True
    assert "associative_replay feature flag not enabled" in r.metadata.get("skipped", "")


@pytest.mark.asyncio
async def test_associative_replay_stub_enabled():
    """Even when enabled flag is True the stub body succeeds (placeholder)."""
    r = await associative_replay(enabled=True)
    assert r.phase == "associative_replay"
    assert r.success is True


# --- Phase 4: affective_reset ---

@pytest.mark.asyncio
async def test_affective_reset_calls_affect():
    t = FakeAffect()
    r = await affective_reset(t)
    assert r.phase == "affective_reset"
    assert r.success is True
    assert t.reset_calls == 1


@pytest.mark.asyncio
async def test_affective_reset_no_affect():
    r = await affective_reset(None)
    assert r.success is True
    assert "skipped" in r.metadata


# --- Full five-phase pipeline ordering via module ---

@pytest.mark.asyncio
async def test_five_phase_pipeline_order_via_module(tmp_path: Path):
    """End-to-end: module._run_pipeline produces exactly the five phases in order."""
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    episodic_memory = FakeFullEpisodicMemory()
    affect = FakeAffect()
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    sleep = Sleep(
        bus,
        episodic_memory=episodic_memory,
        affect=affect,
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )
    summary = await sleep.enter_sleep()
    phases = [p["phase"] for p in summary["phases"]]
    assert phases == [
        "light_consolidation",
        "deep_consolidation",
        "associative_replay",
        "voice_alignment",
        "affective_reset",
    ]
    # Phase 1: consolidation ran
    assert episodic_memory.consolidate_calls == 1
    # Phase 2: downscale ran, replay ran
    assert len(episodic_memory.downscale_calls) == 1
    assert episodic_memory.replay_calls == 1
    # Phase 5: the affect module's reset ran, last.
    assert affect.reset_calls == 1

    await bus.close()


# --- Fatigue reset via sleep.sleep.completed event ---

@pytest.mark.asyncio
async def test_fatigue_reset_on_sleep_completed(tmp_path: Path):
    """Phase 4 must cause the interoception module to reset its fatigue accumulator.

    The reset path is: the sleep module publishes sleep.sleep.completed →
    Interoception._sleep_event_loop calls self._fatigue.reset().
    We verify this by checking the event is published after pipeline completion
    (the actual interoception module wiring is an integration concern tested in test_interoception_sleep_flag.py).
    """
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    sleep = Sleep(
        bus,
        episodic_memory=FakeFullEpisodicMemory(),
        affect=FakeAffect(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )
    await sleep.enter_sleep()

    # sleep.sleep.completed MUST be published (the interoception module resets on this event)
    entries = await bus.read("sleep.out", last_id="0", count=20)
    types = [e.type for _, e in entries]
    assert "sleep.sleep.completed" in types, (
        "sleep.sleep.completed must be published so Soma can reset fatigue"
    )

    await bus.close()
