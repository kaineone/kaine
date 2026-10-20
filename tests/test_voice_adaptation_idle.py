# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Voice adaptation idle behaviour for Stage 0/1.

Voice alignment must remain idle while no validated preference source exists:
it builds no DPO pairs, emits no consolidation divergence signal, and writes
no consolidation_divergence.json state file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import kaine.modules.sleep.module as sleep_module
import kaine.modules.sleep.voice_alignment as voice_alignment_module
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.sleep import TrainingResult
from kaine.modules.sleep.corpus import intent_record_paths
from kaine.modules.sleep.module import Sleep
from kaine.modules.sleep.voice_alignment import (
    OPERATOR_APPROVED_ENV,
    DPOPairBuilder,
    FakeTrainer,
    VoiceAlignmentConfig,
)


class _FakeEpisodicMemory:
    async def consolidate_now(self) -> int:
        return 0

    async def downscale(self, protect=()):
        return {"n_new": 0, "factor": 1.0, "protected": len(list(protect)), "total_before": 0.0, "total_after": 0.0, "silent": 0}

    async def replay_now(self) -> list:
        return []


class _FakeAffect:
    async def affective_reset(self) -> None:
        return None


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


# A mix of identical (no signal), divergent (usable), and degenerate records
# so the exact rate is computable: 5 scanned, 2 usable -> rate 0.4.
_MIXED = [
    {"prompt": "a", "faithful_rendering": "truth-1", "generated_text": "bare-1"},  # usable
    {"prompt": "b", "faithful_rendering": "same", "generated_text": "same"},       # identical
    {"prompt": "c", "faithful_rendering": "truth-3", "generated_text": "bare-3"},  # usable
    {"prompt": "d", "faithful_rendering": "", "generated_text": "bare-4"},         # no chosen
    {"prompt": "e", "faithful_rendering": "truth-5", "generated_text": "truth-5"}, # identical
]


def _divergent_records(n: int) -> list[dict]:
    return [
        {"prompt": "p", "faithful_rendering": f"truth {i}", "generated_text": f"generated {i}"}
        for i in range(n)
    ]


def _make_sleep(
    bus: AsyncBus,
    tmp_path: Path,
    *,
    intent_records: list[dict] | None,
    enabled: bool = True,
    trainer=None,
) -> Sleep:
    log_path = tmp_path / "intent.jsonl"
    if intent_records is not None:
        _write_jsonl(log_path, intent_records)
    config = VoiceAlignmentConfig(
        intent_log_path=log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=enabled,
        preference_source="none",
    )
    return Sleep(
        bus,
        episodic_memory=_FakeEpisodicMemory(),
        affect=_FakeAffect(),
        trainer=trainer or FakeTrainer(),
        voice_alignment_config=config,
    )


class _RecordingTrainer:
    def __init__(self) -> None:
        self.calls: list[list] = []

    async def train(self, pairs, config):
        self.calls.append(list(pairs))
        return TrainingResult(
            accepted=True,
            adapter_path=None,
            capability_loss=0.0,
            reason="recorded",
            samples_used=len(pairs),
        )


def _spy_build(sleep: Sleep):
    calls = []
    original = sleep._builder.build_with_counts
    def wrapper(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)
    sleep._builder.build_with_counts = wrapper
    return calls


def test_build_with_counts_exact_rate(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    _write_jsonl(p, _MIXED)
    pairs, scanned, usable = DPOPairBuilder().build_with_counts(p, max_pairs=100)
    assert scanned == 5
    assert usable == 2
    assert len(pairs) == 2
    assert usable / max(1, scanned) == pytest.approx(0.4)


def test_usable_counts_full_numerator_past_max_pairs(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    _write_jsonl(
        p,
        [
            {"prompt": str(i), "faithful_rendering": f"t{i}", "generated_text": f"g{i}"}
            for i in range(6)
        ],
    )
    pairs, scanned, usable = DPOPairBuilder().build_with_counts(p, max_pairs=2)
    assert len(pairs) == 2
    assert scanned == 6
    assert usable == 6


def test_build_missing_file_zero_counts(tmp_path: Path):
    pairs, scanned, usable = DPOPairBuilder().build_with_counts(
        tmp_path / "missing.jsonl", max_pairs=10
    )
    assert (pairs, scanned, usable) == ([], 0, 0)


@pytest.mark.asyncio
async def test_disabled_voice_alignment_builds_no_pairs(bus, tmp_path, monkeypatch):
    monkeypatch.delenv(OPERATOR_APPROVED_ENV, raising=False)
    sleep = _make_sleep(bus, tmp_path, intent_records=_divergent_records(20), enabled=False)
    calls = _spy_build(sleep)
    before = sleep._sleep_count
    voice_result, phase = await sleep._run_voice_alignment()
    assert sleep._sleep_count == before
    assert voice_result.accepted is False
    assert voice_result.samples_used == 0
    assert phase.success is True
    assert phase.metadata.get("skipped") == "config disabled"
    assert calls == []
    entries = await bus.read("sleep.out", count=50)
    assert not any(e.type == "sleep.consolidation_divergence" for _, e in entries)
    assert not list(tmp_path.rglob("consolidation_divergence.json"))
    assert "consolidation_divergence" not in phase.metadata


@pytest.mark.asyncio
async def test_enabled_approved_without_validated_source_builds_no_pairs(
    bus, tmp_path, monkeypatch,
):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    sleep = _make_sleep(bus, tmp_path, intent_records=_divergent_records(20), enabled=True)
    calls = _spy_build(sleep)
    before = sleep._sleep_count
    voice_result, phase = await sleep._run_voice_alignment()
    assert sleep._sleep_count == before
    assert voice_result.accepted is False
    assert voice_result.samples_used == 0
    assert phase.success is True
    assert "no validated preference source" in phase.metadata.get("skipped", "")
    assert calls == []
    entries = await bus.read("sleep.out", count=50)
    assert not any(e.type == "sleep.consolidation_divergence" for _, e in entries)
    assert not list(tmp_path.rglob("consolidation_divergence.json"))
    assert "consolidation_divergence" not in phase.metadata


@pytest.mark.asyncio
async def test_enabled_approved_with_validated_source_calls_builder_and_trains(
    bus, tmp_path, monkeypatch,
):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    monkeypatch.setattr(sleep_module, "TRAINING_SOURCES", frozenset({"none"}))
    trainer = _RecordingTrainer()
    sleep = _make_sleep(
        bus, tmp_path, intent_records=_divergent_records(20), enabled=True, trainer=trainer
    )
    calls = _spy_build(sleep)
    trained: list = []
    original_train = sleep._train_on_pairs

    async def _spy_train(pairs, start_ms, meta):
        trained.append(list(pairs))
        return await original_train(pairs, start_ms, meta)

    sleep._train_on_pairs = _spy_train
    before = sleep._sleep_count
    voice_result, phase = await sleep._run_voice_alignment()
    assert sleep._sleep_count == before
    assert len(calls) == 1
    args, kwargs = calls[0]
    paths = args[0]
    assert paths == intent_record_paths(
        sleep._voice_config.intent_log_path,
        sleep._voice_config.intent_log_path.parent / "intent_log",
    )
    assert kwargs.get("max_pairs") == sleep._voice_config.max_samples
    # The built pairs reach the training path (which may still drop pairs
    # without a stored system prompt before the trainer runs).
    assert len(trained) == 1
    assert len(trained[0]) == 20
    assert phase.success is True
    entries = await bus.read("sleep.out", count=50)
    assert not any(e.type == "sleep.consolidation_divergence" for _, e in entries)
    assert not list(tmp_path.rglob("consolidation_divergence.json"))
    assert "consolidation_divergence" not in phase.metadata


@pytest.mark.asyncio
async def test_builder_exception_yields_empty_pairs_and_phase_succeeds(
    bus, tmp_path, monkeypatch,
):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    monkeypatch.setattr(sleep_module, "TRAINING_SOURCES", frozenset({"none"}))
    sleep = _make_sleep(bus, tmp_path, intent_records=_divergent_records(20), enabled=True)

    def boom(*args, **kwargs):
        raise RuntimeError("corpus unreadable")

    sleep._builder.build_with_counts = boom
    before = sleep._sleep_count
    voice_result, phase = await sleep._run_voice_alignment()
    assert sleep._sleep_count == before
    assert voice_result.accepted is False
    assert "no usable DPO pairs" in voice_result.reason
    assert voice_result.samples_used == 0
    assert phase.success is True
    assert phase.metadata.get("pairs") == 0
    assert "consolidation_divergence" not in phase.metadata


def test_voice_alignment_module_has_no_consolidation_divergence_api():
    for name in (
        "ConsolidationDivergence",
        "CONSOLIDATION_DIVERGENCE_STATE",
        "consolidation_magnitude",
        "write_consolidation_divergence",
        "read_consolidation_divergence",
    ):
        assert not hasattr(voice_alignment_module, name), name
