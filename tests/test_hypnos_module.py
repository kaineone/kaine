# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
import time
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos import (
    FakeTrainer,
    Hypnos,
    HypnosBusyError,
    RestScheduler,
    Trainer,
    TrainingResult,
    VoiceAlignmentConfig,
)
from kaine.modules.hypnos.voice_alignment import OPERATOR_APPROVED_ENV, DPOPairBuilder


@pytest.fixture(autouse=True)
def _voice_alignment_opt_in(monkeypatch):
    """Existing hypnos tests assume voice-alignment training fires.
    Two-layer safety gate (config.enabled + env var) is set by default
    so the trainer is actually called; tests that want to exercise the
    skip-on-disabled paths override this fixture explicitly."""
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class FakeMnemos:
    def __init__(self) -> None:
        self.consolidated = 0
        self.downscale_calls: list[float] = []
        self.replay_calls = 0

    async def consolidate_now(self) -> int:
        self.consolidated += 1
        return 5

    def downscale_activations(self, factor: float) -> int:
        self.downscale_calls.append(factor)
        return 0

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []


class FakeThymos:
    def __init__(self) -> None:
        self.resets = 0

    async def affective_reset(self) -> None:
        self.resets += 1


# Generic steppable stand-in for the belief-revision phase. Nous no longer
# runs a NAR subprocess; the phase remains a generic "steppable" hook.
class FakeSteppable:
    @property
    def running(self) -> bool:
        return True

    async def step(self, n: int) -> list[str]:
        return ["belief_factor_0"]


class FakeResetter:
    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        self.calls += 1


def _make_hypnos(
    bus: AsyncBus,
    tmp_path: Path,
    *,
    intent_records: list[dict] | None = None,
    trainer: Trainer | None = None,
    mnemos=None,
) -> Hypnos:
    log_path = tmp_path / "intent.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if intent_records is not None:
        with log_path.open("w", encoding="utf-8") as fh:
            for r in intent_records:
                fh.write(json.dumps(r) + "\n")
    config = VoiceAlignmentConfig(
        intent_log_path=log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
    )
    return Hypnos(
        bus,
        mnemos=mnemos or FakeMnemos(),
        nous_process=FakeSteppable(),
        thymos=FakeThymos(),
        chronos_resetters=[FakeResetter(), FakeResetter()],
        trainer=trainer or FakeTrainer(),
        voice_alignment_config=config,
    )


@pytest.mark.asyncio
async def test_invalid_construction(bus: AsyncBus, tmp_path: Path):
    with pytest.raises(ValueError):
        Hypnos(bus, baseline_salience=2.0)
    with pytest.raises(ValueError):
        Hypnos(bus, alert_salience=-0.1)


@pytest.mark.asyncio
async def test_enter_sleep_runs_all_five_phases(bus: AsyncBus, tmp_path: Path):
    hypnos = _make_hypnos(bus, tmp_path)
    summary = await hypnos.enter_sleep()
    phases = [p["phase"] for p in summary["phases"]]
    # Paper §3.3.5 five-phase order (hypnos-fatigue-phases restructure)
    assert phases == [
        "light_consolidation",
        "deep_consolidation",
        "associative_replay",
        "affective_reset",
        "voice_alignment",
    ]
    assert all(p["success"] for p in summary["phases"])
    assert hypnos._mnemos.consolidated == 1
    assert hypnos._thymos.resets == 1


@pytest.mark.asyncio
async def test_sleep_rotates_intent_log(bus: AsyncBus, tmp_path: Path):
    records = [{"intent": "alpha"}, {"intent": "beta"}]
    hypnos = _make_hypnos(bus, tmp_path, intent_records=records)

    summary = await hypnos.enter_sleep()

    rotated = summary["corpus"]["rotated"]
    assert rotated is not None
    corpus_dir = tmp_path / "intent_log"
    assert (corpus_dir / rotated).exists()
    assert not (tmp_path / "intent.jsonl").exists()
    assert summary["corpus"]["corpus_bytes"] > 0

    # A second sleep with no new intent log writes has nothing to rotate.
    summary2 = await hypnos.enter_sleep()
    assert summary2["corpus"]["rotated"] is None


@pytest.mark.asyncio
async def test_rotation_failure_does_not_break_sleep(
    bus: AsyncBus, tmp_path: Path, monkeypatch
):
    records = [{"intent": "alpha"}]
    hypnos = _make_hypnos(bus, tmp_path, intent_records=records)

    captured: list[str] = []

    async def capture_publish(self, stream, data, **kwargs):
        captured.append(stream)

    monkeypatch.setattr(
        "kaine.modules.hypnos.module.Hypnos.publish", capture_publish
    )

    def broken(*args, **kwargs):
        raise RuntimeError("rotation intentionally broken")

    monkeypatch.setattr(
        "kaine.modules.hypnos.module.rotate_intent_log", broken
    )

    summary = await hypnos.enter_sleep()

    assert summary is not None
    assert summary["corpus"]["rotated"] is None
    assert summary["corpus"]["warned"] is False
    assert "hypnos.sleep.completed" in captured


@pytest.mark.asyncio
async def test_started_and_completed_events(bus: AsyncBus, tmp_path: Path):
    hypnos = _make_hypnos(bus, tmp_path)
    await hypnos.enter_sleep()
    entries = await bus.read("hypnos.out", last_id="0", count=20)
    types = [e.type for _, e in entries]
    assert "hypnos.sleep.started" in types
    assert "hypnos.sleep.completed" in types
    completed = next(e for _, e in entries if e.type == "hypnos.sleep.completed")
    assert "phases" in completed.payload
    assert len(completed.payload["phases"]) == 5
    assert "voice_alignment" in completed.payload


@pytest.mark.asyncio
async def test_concurrent_sleep_rejected(bus: AsyncBus, tmp_path: Path):
    """A sleep already in progress rejects a second enter_sleep() call.
    Determinism is provided by holding the first consolidation phase on an
    asyncio.Event, not by relying on training to keep the sleep alive."""
    hold = asyncio.Event()

    class SlowMnemos(FakeMnemos):
        async def consolidate_now(self) -> int:
            await hold.wait()
            self.consolidated += 1
            return 5

    hypnos = _make_hypnos(bus, tmp_path, mnemos=SlowMnemos())
    first = asyncio.create_task(hypnos.enter_sleep())
    await asyncio.sleep(0.01)
    with pytest.raises(HypnosBusyError):
        await hypnos.enter_sleep()
    hold.set()
    await first


@pytest.mark.asyncio
async def test_one_phase_failure_does_not_stop_others(bus: AsyncBus, tmp_path: Path):
    class BoomMnemos:
        """Mnemos stub where consolidate_now raises; other methods succeed."""
        async def consolidate_now(self) -> int:
            raise RuntimeError("boom")

        def downscale_activations(self, factor: float) -> int:
            return 0

        async def replay_now(self) -> list:
            return []

    hypnos = Hypnos(
        bus,
        mnemos=BoomMnemos(),
        nous_process=FakeSteppable(),
        thymos=FakeThymos(),
        chronos_resetters=[FakeResetter()],
        trainer=FakeTrainer(),
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=tmp_path / "missing.jsonl",
            adapter_output_dir=tmp_path / "adapters",
        ),
    )
    summary = await hypnos.enter_sleep()
    phases = {p["phase"]: p for p in summary["phases"]}
    # Phase 1 (light_consolidation) calls consolidate_now which raises here.
    assert phases["light_consolidation"]["success"] is False
    # Remaining phases must still complete (non-interruptible pipeline).
    assert phases["deep_consolidation"]["success"] is True
    assert phases["affective_reset"]["success"] is True


@pytest.mark.asyncio
async def test_voice_alignment_skips_when_no_pairs(bus: AsyncBus, tmp_path: Path):
    """With the fail-closed Stage 0 gate, an empty intent log still reaches the
    'no validated preference source' skip before the no-pairs branch."""
    hypnos = _make_hypnos(bus, tmp_path, intent_records=[])
    summary = await hypnos.enter_sleep()
    voice = summary["voice_alignment"]
    assert voice["accepted"] is False
    assert "no validated preference source" in voice["reason"]
    assert len(hypnos._trainer.calls) == 0


@pytest.mark.asyncio
async def test_voice_alignment_passes_pairs_to_trainer(bus: AsyncBus, tmp_path: Path):
    trainer = FakeTrainer()
    hypnos = _make_hypnos(
        bus, tmp_path,
        intent_records=[
            {"prompt": "p1", "faithful_rendering": "t1", "generated_text": "g1"},
            {"prompt": "p2", "faithful_rendering": "t2", "generated_text": "g2"},
        ],
        trainer=trainer,
    )
    pairs = DPOPairBuilder().build(
        hypnos._voice_config.intent_log_path,
        max_pairs=hypnos._voice_config.max_samples,
    )
    start_ms = time.monotonic() * 1000.0
    def _meta(extra):
        return dict(extra)
    voice_result, phase_result = await hypnos._train_on_pairs(pairs, start_ms, _meta)

    assert len(trainer.calls) == 1
    pair_count, _cfg = trainer.calls[0]
    assert pair_count == 2
    assert phase_result.success is True


@pytest.mark.asyncio
async def test_capability_loss_veto(bus: AsyncBus, tmp_path: Path):
    """If the trainer accepts but capability loss exceeds threshold,
    Hypnos vetoes the result and reports it as rejected."""
    class BigLossTrainer:
        async def train(self, pairs, config):
            adapter = config.adapter_output_dir / "would-be-adapter"
            adapter.mkdir(parents=True, exist_ok=True)
            return TrainingResult(
                accepted=True,
                adapter_path=adapter,
                capability_loss=0.5,  # well above default 0.05
                reason="trainer accepted",
                samples_used=len(pairs),
            )

    hypnos = _make_hypnos(
        bus, tmp_path,
        intent_records=[{"prompt": "p", "faithful_rendering": "t", "generated_text": "g"}],
        trainer=BigLossTrainer(),
    )
    pairs = DPOPairBuilder().build(
        hypnos._voice_config.intent_log_path,
        max_pairs=hypnos._voice_config.max_samples,
    )
    start_ms = time.monotonic() * 1000.0
    def _meta(extra):
        return dict(extra)
    voice_result, phase_result = await hypnos._train_on_pairs(pairs, start_ms, _meta)

    assert voice_result.accepted is False
    assert "capability loss" in voice_result.reason.lower()
    assert phase_result.success is True


@pytest.mark.asyncio
async def test_scheduler_marked_completed_after_sleep(bus: AsyncBus, tmp_path: Path):
    hypnos = _make_hypnos(bus, tmp_path)
    now = [0.0]
    hypnos._scheduler = RestScheduler(
        interval_seconds=60,
        max_deferral_seconds=120,
        per_defer_seconds=10,
        clock=lambda: now[0],
    )
    now[0] = 100.0  # now sleep is due
    assert hypnos.is_due() is True
    await hypnos.enter_sleep()
    # After completion, next due time should be in the future relative to now.
    assert hypnos.is_due() is False


@pytest.mark.asyncio
async def test_serialize_yields_state(bus: AsyncBus, tmp_path: Path):
    hypnos = _make_hypnos(bus, tmp_path)
    state = hypnos.serialize()
    assert "last_sleep_at" in state
    assert "original_due_at" in state


@pytest.mark.asyncio
async def test_is_sleeping_flag(bus: AsyncBus, tmp_path: Path):
    hypnos = _make_hypnos(bus, tmp_path)
    assert hypnos.is_sleeping is False
    await hypnos.enter_sleep()
    assert hypnos.is_sleeping is False  # released after completion
