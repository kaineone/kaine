# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
import time
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.sleep import (
    FakeTrainer,
    RestScheduler,
    Sleep,
    SleepBusyError,
    Trainer,
    TrainingResult,
    VoiceAlignmentConfig,
)
from kaine.modules.sleep.voice_alignment import OPERATOR_APPROVED_ENV, DPOPairBuilder
from tests.voice_prompt_support import with_verified_system


@pytest.fixture(autouse=True)
def _voice_alignment_opt_in(monkeypatch):
    """Existing sleep module tests assume voice-alignment training fires.
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

    async def downscale(self, protect=()):
        protect = list(protect)
        self.downscale_calls.append(protect)
        return {"n_new": 0, "factor": 1.0, "protected": len(protect), "total_before": 0.0, "total_after": 0.0, "pruned_floor": 0, "pruned_budget": 0, "store_bytes": 0}

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []


class FakeThymos:
    def __init__(self) -> None:
        self.resets = 0

    async def affective_reset(self) -> None:
        self.resets += 1


class FakeResetter:
    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        self.calls += 1


def _make_sleep(
    bus: AsyncBus,
    tmp_path: Path,
    *,
    intent_records: list[dict] | None = None,
    trainer: Trainer | None = None,
    episodic_memory=None,
) -> Sleep:
    log_path = tmp_path / "intent.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if intent_records is not None:
        with log_path.open("w", encoding="utf-8") as fh:
            for r in with_verified_system(log_path, intent_records):
                fh.write(json.dumps(r) + "\n")
    config = VoiceAlignmentConfig(
        intent_log_path=log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
    )
    return Sleep(
        bus,
        episodic_memory=episodic_memory or FakeMnemos(),
        affect=FakeThymos(),
        sequence_resetters=[FakeResetter(), FakeResetter()],
        trainer=trainer or FakeTrainer(),
        voice_alignment_config=config,
    )


@pytest.mark.asyncio
async def test_invalid_construction(bus: AsyncBus, tmp_path: Path):
    with pytest.raises(ValueError):
        Sleep(bus, baseline_salience=2.0)
    with pytest.raises(ValueError):
        Sleep(bus, alert_salience=-0.1)


@pytest.mark.asyncio
async def test_enter_sleep_runs_all_five_phases(bus: AsyncBus, tmp_path: Path):
    sleep = _make_sleep(bus, tmp_path)
    summary = await sleep.enter_sleep()
    phases = [p["phase"] for p in summary["phases"]]
    # Paper §3.5 order: sleep ends with the affective reset
    assert phases == [
        "light_consolidation",
        "deep_consolidation",
        "associative_replay",
        "voice_alignment",
        "affective_reset",
    ]
    assert all(p["success"] for p in summary["phases"])
    assert sleep._episodic_memory.consolidated == 1
    assert sleep._affect.resets == 1
    assert summary["memory_pruned_floor"] == 0
    assert summary["memory_pruned_budget"] == 0
    assert summary["memory_store_bytes"] == 0


@pytest.mark.asyncio
async def test_voice_alignment_abort_still_resets_affect(bus: AsyncBus, tmp_path: Path):
    """Sleep ends with the affective reset even when voice alignment raises."""
    sleep = _make_sleep(bus, tmp_path)

    async def _boom():
        raise RuntimeError("voice boom")

    sleep._run_voice_alignment = _boom
    with pytest.raises(RuntimeError, match="voice boom"):
        await sleep.enter_sleep()
    assert sleep._affect.resets == 1


@pytest.mark.asyncio
async def test_sleep_writes_voice_measures_latest(bus: AsyncBus, tmp_path: Path):
    intent_records = [
        {"generated_text": "hello world this is a test.", "faithful_rendering": "x"}
        for _ in range(3)
    ]
    sleep = _make_sleep(bus, tmp_path, intent_records=intent_records)
    summary = await sleep.enter_sleep()

    latest = tmp_path / "voice_measures_latest.json"
    assert latest.is_file()
    vm = summary["voice_measures"]
    assert vm is not None
    assert vm["utterance_count"] == 3
    assert vm["distinctiveness"] is None  # no shipped base profile yet


@pytest.mark.asyncio
async def test_voice_measures_failure_does_not_break_sleep(
    bus: AsyncBus, tmp_path: Path, monkeypatch
):
    def _boom(*args, **kwargs):
        raise RuntimeError("measures boom")

    monkeypatch.setattr(
        "kaine.modules.sleep.module.compute_sleep_measures", _boom
    )
    intent_records = [
        {"generated_text": "a b c d e f g", "faithful_rendering": "x"}
    ]
    sleep = _make_sleep(bus, tmp_path, intent_records=intent_records)
    stale_path = tmp_path / "voice_measures_latest.json"
    stale_path.write_text(json.dumps({"distinctiveness": 0.01}), encoding="utf-8")
    summary = await sleep.enter_sleep()
    assert all(p["success"] for p in summary["phases"])
    assert summary.get("voice_measures") is None
    assert sleep._episodic_memory.consolidated == 1
    assert sleep._affect.resets == 1
    latest_path = tmp_path / "voice_measures_latest.json"
    assert latest_path.exists()
    data = json.loads(latest_path.read_text(encoding="utf-8"))
    assert data.get("measurement_failed") is True
    assert "timestamp" in data
    assert "distinctiveness" not in data


@pytest.mark.asyncio
async def test_sleep_rotates_intent_log(bus: AsyncBus, tmp_path: Path):
    records = [{"intent": "alpha"}, {"intent": "beta"}]
    sleep = _make_sleep(bus, tmp_path, intent_records=records)

    summary = await sleep.enter_sleep()

    rotated = summary["corpus"]["rotated"]
    assert "error" not in summary["corpus"]
    assert rotated is not None
    corpus_dir = tmp_path / "intent_log"
    assert (corpus_dir / rotated).exists()
    assert not (tmp_path / "intent.jsonl").exists()
    assert summary["corpus"]["corpus_bytes"] > 0

    # A second sleep with no new intent log writes has nothing to rotate.
    summary2 = await sleep.enter_sleep()
    assert summary2["corpus"]["rotated"] is None


@pytest.mark.asyncio
async def test_rotation_failure_does_not_break_sleep(
    bus: AsyncBus, tmp_path: Path, monkeypatch
):
    records = [{"intent": "alpha"}]
    sleep = _make_sleep(bus, tmp_path, intent_records=records)

    captured: list[str] = []

    async def capture_publish(self, stream, data, **kwargs):
        captured.append(stream)

    monkeypatch.setattr(
        "kaine.modules.sleep.module.Sleep.publish", capture_publish
    )

    def broken(*args, **kwargs):
        raise RuntimeError("rotation intentionally broken")

    monkeypatch.setattr(
        "kaine.modules.sleep.module.rotate_intent_log", broken
    )

    summary = await sleep.enter_sleep()

    assert summary is not None
    assert summary["corpus"]["rotated"] is None
    assert summary["corpus"]["warned"] is False
    assert summary["corpus"]["error"] == "RuntimeError: rotation intentionally broken"
    assert "hypnos.sleep.completed" in captured


@pytest.mark.asyncio
async def test_rotation_failure_marks_measurement_failed(
    bus: AsyncBus, tmp_path: Path, monkeypatch
):
    records = [{"intent": "alpha"}]
    sleep = _make_sleep(bus, tmp_path, intent_records=records)

    stale_path = tmp_path / "voice_measures_latest.json"
    stale_path.write_text(json.dumps({"distinctiveness": 0.01}), encoding="utf-8")

    def broken(*args, **kwargs):
        raise RuntimeError("rotation intentionally broken")

    monkeypatch.setattr(
        "kaine.modules.sleep.module.rotate_intent_log", broken
    )

    summary = await sleep.enter_sleep()

    assert summary is not None
    assert summary["corpus"]["rotated"] is None
    assert summary["corpus"]["error"] == "RuntimeError: rotation intentionally broken"
    assert summary.get("voice_measures") is None
    latest_path = tmp_path / "voice_measures_latest.json"
    assert latest_path.exists()
    data = json.loads(latest_path.read_text(encoding="utf-8"))
    assert data.get("measurement_failed") is True
    assert "timestamp" in data
    assert "distinctiveness" not in data


@pytest.mark.asyncio
async def test_ceiling_failure_after_rotation_keeps_the_fresh_measurement(
    bus: AsyncBus, tmp_path: Path, monkeypatch
):
    """Only a rotation that raised is a failed measurement: a corpus-ceiling
    check failing after a good rotation must not overwrite the fresh measure."""
    intent_records = [
        {"generated_text": "hello world this is a test.", "faithful_rendering": "x"}
        for _ in range(3)
    ]
    sleep = _make_sleep(bus, tmp_path, intent_records=intent_records)

    def broken_ceiling(*args, **kwargs):
        raise RuntimeError("ceiling check intentionally broken")

    monkeypatch.setattr(
        "kaine.modules.sleep.module.check_corpus_ceiling", broken_ceiling
    )
    summary = await sleep.enter_sleep()

    assert summary["corpus"]["rotated"] is not None
    data = json.loads((tmp_path / "voice_measures_latest.json").read_text(encoding="utf-8"))
    assert "measurement_failed" not in data
    assert data["utterance_count"] == 3


@pytest.mark.asyncio
async def test_started_and_completed_events(bus: AsyncBus, tmp_path: Path):
    sleep = _make_sleep(bus, tmp_path)
    await sleep.enter_sleep()
    entries = await bus.read("hypnos.out", last_id="0", count=20)
    types = [e.type for _, e in entries]
    assert "hypnos.sleep.started" in types
    assert "hypnos.sleep.completed" in types
    completed = next(e for _, e in entries if e.type == "hypnos.sleep.completed")
    assert "phases" in completed.payload
    assert len(completed.payload["phases"]) == 5
    assert "voice_alignment" in completed.payload
    assert completed.payload["alert"] is (completed.salience != sleep._baseline_salience)


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

    sleep = _make_sleep(bus, tmp_path, episodic_memory=SlowMnemos())
    first = asyncio.create_task(sleep.enter_sleep())
    await asyncio.sleep(0.01)
    with pytest.raises(SleepBusyError):
        await sleep.enter_sleep()
    hold.set()
    await first


@pytest.mark.asyncio
async def test_one_phase_failure_does_not_stop_others(bus: AsyncBus, tmp_path: Path):
    class BoomMnemos:
        """The episodic memory module stub where consolidate_now raises; other methods succeed."""
        async def consolidate_now(self) -> int:
            raise RuntimeError("boom")

        async def downscale(self, protect=()):
            protect = list(protect)
            return {"n_new": 0, "factor": 1.0, "protected": len(protect), "total_before": 0.0, "total_after": 0.0, "silent": 0}

        async def replay_now(self) -> list:
            return []

    sleep = Sleep(
        bus,
        episodic_memory=BoomMnemos(),
        affect=FakeThymos(),
        sequence_resetters=[FakeResetter()],
        trainer=FakeTrainer(),
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=tmp_path / "missing.jsonl",
            adapter_output_dir=tmp_path / "adapters",
        ),
    )
    summary = await sleep.enter_sleep()
    phases = {p["phase"]: p for p in summary["phases"]}
    # Phase 1 (light_consolidation) calls consolidate_now which raises here.
    assert phases["light_consolidation"]["success"] is False
    # Remaining phases must still complete (non-interruptible pipeline).
    assert phases["deep_consolidation"]["success"] is True
    assert phases["affective_reset"]["success"] is True


@pytest.mark.asyncio
async def test_voice_alignment_skips_without_preference_source_even_with_empty_log(bus: AsyncBus, tmp_path: Path):
    """With the fail-closed Stage 0 gate, an empty intent log still reaches the
    'no validated preference source' skip before the no-pairs branch."""
    sleep = _make_sleep(bus, tmp_path, intent_records=[])
    summary = await sleep.enter_sleep()
    voice = summary["voice_alignment"]
    assert voice["accepted"] is False
    assert "no validated preference source" in voice["reason"]
    assert len(sleep._trainer.calls) == 0


@pytest.mark.asyncio
async def test_voice_alignment_passes_pairs_to_trainer(bus: AsyncBus, tmp_path: Path):
    trainer = FakeTrainer()
    sleep = _make_sleep(
        bus, tmp_path,
        intent_records=[
            {"prompt": "p1", "faithful_rendering": "t1", "generated_text": "g1"},
            {"prompt": "p2", "faithful_rendering": "t2", "generated_text": "g2"},
        ],
        trainer=trainer,
    )
    pairs = DPOPairBuilder().build(
        sleep._voice_config.intent_log_path,
        max_pairs=sleep._voice_config.max_samples,
    )
    start_ms = time.monotonic() * 1000.0
    def _meta(extra):
        return dict(extra)
    voice_result, phase_result = await sleep._train_on_pairs(pairs, start_ms, _meta)

    assert len(trainer.calls) == 1
    pair_count, _cfg = trainer.calls[0]
    assert pair_count == 2
    assert phase_result.success is True


@pytest.mark.asyncio
async def test_capability_loss_veto(bus: AsyncBus, tmp_path: Path):
    """If the trainer accepts but capability loss exceeds threshold,
    The sleep module vetoes the result and reports it as rejected."""
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

    sleep = _make_sleep(
        bus, tmp_path,
        intent_records=[{"prompt": "p", "faithful_rendering": "t", "generated_text": "g"}],
        trainer=BigLossTrainer(),
    )
    pairs = DPOPairBuilder().build(
        sleep._voice_config.intent_log_path,
        max_pairs=sleep._voice_config.max_samples,
    )
    start_ms = time.monotonic() * 1000.0
    def _meta(extra):
        return dict(extra)
    voice_result, phase_result = await sleep._train_on_pairs(pairs, start_ms, _meta)

    assert voice_result.accepted is False
    assert "capability loss" in voice_result.reason.lower()
    assert phase_result.success is True


@pytest.mark.asyncio
async def test_scheduler_marked_completed_after_sleep(bus: AsyncBus, tmp_path: Path):
    sleep = _make_sleep(bus, tmp_path)
    now = [0.0]
    sleep._scheduler = RestScheduler(
        interval_seconds=60,
        max_deferral_seconds=120,
        per_defer_seconds=10,
        clock=lambda: now[0],
    )
    now[0] = 100.0  # now sleep is due
    assert sleep.is_due() is True
    await sleep.enter_sleep()
    # After completion, next due time should be in the future relative to now.
    assert sleep.is_due() is False


@pytest.mark.asyncio
async def test_serialize_yields_state(bus: AsyncBus, tmp_path: Path):
    sleep = _make_sleep(bus, tmp_path)
    state = sleep.serialize()
    assert "last_sleep_at" in state
    assert "original_due_at" in state


@pytest.mark.asyncio
async def test_is_sleeping_flag(bus: AsyncBus, tmp_path: Path):
    sleep = _make_sleep(bus, tmp_path)
    assert sleep.is_sleeping is False
    await sleep.enter_sleep()
    assert sleep.is_sleeping is False  # released after completion
