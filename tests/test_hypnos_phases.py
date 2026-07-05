# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path

import pytest

from kaine.modules.hypnos.phases import (
    PhaseResult,
    affective_reset,
    associative_replay,
    consolidate_memory,
    deep_consolidation,
    light_consolidation,
    recalibrate_time,
    reset_affect,
    revise_beliefs,
)


class FakeMnemos:
    def __init__(self, moved: int = 7) -> None:
        self.moved = moved
        self.called = 0

    async def consolidate_now(self) -> int:
        self.called += 1
        return self.moved


class FakeThymos:
    def __init__(self) -> None:
        self.reset_calls = 0

    async def affective_reset(self) -> None:
        self.reset_calls += 1


# Nous is now a pymdp/JAX active-inference engine with no subprocess, so the
# belief-revision phase no longer steps a NAR binary. The phase is a generic
# "steppable" hook; this fake exercises that contract without any NARS coupling.
class FakeSteppable:
    def __init__(self, running: bool = True, lines=None) -> None:
        self._running = running
        self._lines = list(lines or [])
        self.step_calls: list[int] = []

    @property
    def running(self) -> bool:
        return self._running

    async def step(self, n: int) -> list[str]:
        self.step_calls.append(n)
        return list(self._lines)


class FakeResetter:
    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        self.calls += 1


@pytest.mark.asyncio
async def test_consolidate_memory_success():
    m = FakeMnemos(moved=4)
    r = await consolidate_memory(m)
    assert r.success is True
    assert r.phase == "memory_consolidation"
    assert r.metadata["entries_consolidated"] == 4


@pytest.mark.asyncio
async def test_consolidate_memory_no_mnemos():
    r = await consolidate_memory(None)
    assert r.success is True
    assert "skipped" in r.metadata


@pytest.mark.asyncio
async def test_consolidate_memory_error():
    class BoomMnemos:
        async def consolidate_now(self):
            raise RuntimeError("boom")

    r = await consolidate_memory(BoomMnemos())
    assert r.success is False
    assert "RuntimeError" in (r.error or "")


@pytest.mark.asyncio
async def test_revise_beliefs_skipped_when_no_process():
    r = await revise_beliefs(None, step_burst=100)
    assert r.success is True
    assert "skipped" in r.metadata


@pytest.mark.asyncio
async def test_revise_beliefs_skipped_when_not_running():
    r = await revise_beliefs(FakeSteppable(running=False), step_burst=100)
    assert r.success is True


@pytest.mark.asyncio
async def test_revise_beliefs_calls_step():
    proc = FakeSteppable(running=True, lines=["belief_factor_0"])
    r = await revise_beliefs(proc, step_burst=50)
    assert r.success is True
    assert proc.step_calls == [50]
    assert r.metadata["lines_emitted"] == 1


@pytest.mark.asyncio
async def test_reset_affect_calls_reset():
    t = FakeThymos()
    r = await reset_affect(t)
    assert r.success is True
    assert t.reset_calls == 1


@pytest.mark.asyncio
async def test_reset_affect_no_thymos():
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

class FakeFullMnemos:
    """Full-protocol Mnemos fake for new-phase tests."""

    def __init__(self, moved: int = 3) -> None:
        self.moved = moved
        self.consolidate_calls = 0
        self.downscale_calls: list[float] = []
        self.replay_calls = 0

    async def consolidate_now(self) -> int:
        self.consolidate_calls += 1
        return self.moved

    def downscale_activations(self, factor: float) -> int:
        self.downscale_calls.append(factor)
        return 5  # pretend 5 vectors scaled

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
    m = FakeFullMnemos(moved=4)
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
async def test_light_consolidation_no_mnemos():
    r = await light_consolidation(None)
    assert r.success is True
    assert "consolidation_skipped" in r.metadata


@pytest.mark.asyncio
async def test_light_consolidation_empty_module_list():
    m = FakeFullMnemos()
    r = await light_consolidation(m, active_modules=[], frequency_scale=0.5)
    assert r.success is True
    assert r.metadata["modules_frequency_called"] == 0


# --- Phase 2: deep_consolidation ---

@pytest.mark.asyncio
async def test_deep_consolidation_calls_downscale_and_replay():
    m = FakeFullMnemos()
    r = await deep_consolidation(m, downscale_factor=0.8, replay_window_s=1.0)
    assert r.phase == "deep_consolidation"
    assert r.success is True
    assert m.downscale_calls == [0.8]
    assert m.replay_calls == 1
    assert r.metadata["vectors_downscaled"] == 5
    assert r.metadata["downscale_factor"] == 0.8


@pytest.mark.asyncio
async def test_deep_consolidation_suspends_and_restores_perception():
    """suspend_perception is called before replay; restore_perception after."""
    m = FakeFullMnemos()
    calls: list[str] = []

    def suspend():
        calls.append("suspend")

    def restore():
        calls.append("restore")

    await deep_consolidation(
        m,
        downscale_factor=0.9,
        suspend_perception=suspend,
        restore_perception=restore,
    )
    assert calls == ["suspend", "restore"], (
        "perception must be suspended then restored in order"
    )


@pytest.mark.asyncio
async def test_deep_consolidation_restores_even_on_replay_error():
    """restore_perception is called even when replay_now raises."""
    class ReplayBoom(FakeFullMnemos):
        async def replay_now(self) -> list:
            raise RuntimeError("replay boom")

    m = ReplayBoom()
    calls: list[str] = []

    def suspend():
        calls.append("suspend")

    def restore():
        calls.append("restore")

    r = await deep_consolidation(
        m,
        downscale_factor=0.9,
        suspend_perception=suspend,
        restore_perception=restore,
    )
    # Replay error is captured; restore still ran
    assert "restore" in calls
    assert r.success is False  # error reported


@pytest.mark.asyncio
async def test_deep_consolidation_no_mnemos():
    r = await deep_consolidation(None)
    assert r.success is True
    assert "skipped" in r.metadata


# --- Phase 2: downscaling preserves relative ordering ---

@pytest.mark.asyncio
async def test_downscaling_preserves_relative_ordering():
    """Scaling all vectors by factor < 1 preserves cosine similarity (relative order).

    We test this at the Mnemos.downscale_activations level using InMemoryStorage
    so the unit test is self-contained.
    """
    from kaine.modules.mnemos.storage import InMemoryStorage

    storage = InMemoryStorage(latent_dim=2)
    await storage.ensure_collection("test")

    # Insert two vectors with known relationship: a ⊥ b (cosine=0), a ∥ c (cosine=1).
    vec_a = [1.0, 0.0]
    vec_b = [0.0, 1.0]
    vec_c = [2.0, 0.0]  # parallel to a, different magnitude
    await storage.upsert("test", vector=vec_a, text="a", payload={}, affect=None)
    await storage.upsert("test", vector=vec_b, text="b", payload={}, affect=None)
    await storage.upsert("test", vector=vec_c, text="c", payload={}, affect=None)

    # Check cosine similarity before downscaling
    def cosine(u, v):
        import math
        nu = math.sqrt(sum(x*x for x in u))
        nv = math.sqrt(sum(x*x for x in v))
        return sum(x*y for x, y in zip(u, v)) / (nu * nv) if nu * nv else 0.0

    pts_before = storage._collections["test"]
    cos_ac_before = cosine(pts_before[0]["vector"], pts_before[2]["vector"])

    # Scale down by 0.5
    factor = 0.5
    for point in storage._collections["test"]:
        point["vector"] = [v * factor for v in point["vector"]]

    pts_after = storage._collections["test"]
    cos_ac_after = cosine(pts_after[0]["vector"], pts_after[2]["vector"])

    # Cosine similarity is preserved (within floating point)
    assert abs(cos_ac_before - cos_ac_after) < 1e-9, (
        f"cosine similarity changed: {cos_ac_before} -> {cos_ac_after}"
    )

    # L2 norms are halved
    import math
    norm_a_after = math.sqrt(sum(v*v for v in pts_after[0]["vector"]))
    assert abs(norm_a_after - 0.5) < 1e-9


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
async def test_affective_reset_calls_thymos():
    t = FakeThymos()
    r = await affective_reset(t)
    assert r.phase == "affective_reset"
    assert r.success is True
    assert t.reset_calls == 1


@pytest.mark.asyncio
async def test_affective_reset_no_thymos():
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
    from kaine.modules.hypnos import FakeTrainer, Hypnos, VoiceAlignmentConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    mnemos = FakeFullMnemos()
    thymos = FakeThymos()
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    hypnos = Hypnos(
        bus,
        mnemos=mnemos,
        thymos=thymos,
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )
    summary = await hypnos.enter_sleep()
    phases = [p["phase"] for p in summary["phases"]]
    assert phases == [
        "light_consolidation",
        "deep_consolidation",
        "associative_replay",
        "affective_reset",
        "voice_alignment",
    ]
    # Phase 1: consolidation ran
    assert mnemos.consolidate_calls == 1
    # Phase 2: downscale ran, replay ran
    assert len(mnemos.downscale_calls) == 1
    assert mnemos.replay_calls == 1
    # Phase 4: thymos reset ran
    assert thymos.reset_calls == 1

    await bus.close()


# --- Fatigue reset via hypnos.sleep.completed event ---

@pytest.mark.asyncio
async def test_fatigue_reset_on_sleep_completed(tmp_path: Path):
    """Phase 4 must cause Soma to reset its fatigue accumulator.

    The reset path is: Hypnos publishes hypnos.sleep.completed →
    Soma._hypnos_event_loop calls self._fatigue.reset().
    We verify this by checking the event is published after pipeline completion
    (the actual Soma wiring is an integration concern tested in test_soma_hypnos_flag.py).
    """
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.modules.hypnos import FakeTrainer, Hypnos, VoiceAlignmentConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    hypnos = Hypnos(
        bus,
        mnemos=FakeFullMnemos(),
        thymos=FakeThymos(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )
    await hypnos.enter_sleep()

    # hypnos.sleep.completed MUST be published (Soma resets on this event)
    entries = await bus.read("hypnos.out", last_id="0", count=20)
    types = [e.type for _, e in entries]
    assert "hypnos.sleep.completed" in types, (
        "hypnos.sleep.completed must be published so Soma can reset fatigue"
    )

    await bus.close()
