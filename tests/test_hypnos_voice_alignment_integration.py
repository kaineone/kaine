# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""End-to-end Hypnos voice-alignment integration.

Exercises the real UnslothDPOTrainer wired against a FakeBackend through
_hypnos._train_on_pairs. Asserts that the returned TrainingResult/PhaseResult
carry the fields the evaluation sidecar's voice_tracking observer consumes.
"""
from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos import Hypnos, VoiceAlignmentConfig
from kaine.modules.hypnos.capability_eval import (
    NoopAbliterationScorer,
    NoopCapabilityEval,
)
from kaine.modules.hypnos.voice_alignment import OPERATOR_APPROVED_ENV, DPOPairBuilder
from tests.voice_prompt_support import with_verified_system

# With preference_source="none", a sleep never reaches the trainer, so these
# tests call _train_on_pairs directly and check the returned result.


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture(autouse=True)
def _gates_open(monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    for name in ("unsloth", "trl", "peft", "datasets"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    yield


class FakeBackend:
    def load_model(self, **kw):
        return ("fake-model", "fake-tokenizer")

    def run_dpo(self, **kw):
        return 0.31

    def save_adapter(self, *, model, tokenizer, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "adapter_model.safetensors").write_text("fake", encoding="utf-8")


@pytest.mark.asyncio
async def test_training_result_carries_voice_tracking_fields(
    bus: AsyncBus, tmp_path: Path,
):
    """Calling ``_train_on_pairs`` directly returns a result carrying the
    voice-tracking fields; no sleep and no published event are involved."""
    log_path = tmp_path / "intent.jsonl"
    log_path.write_text(
        "\n".join(
            json.dumps(r)
            for r in with_verified_system(
                log_path,
                [
                    {"prompt": f"p{i}", "faithful_rendering": f"t{i}", "generated_text": f"g{i}"}
                    for i in range(2)
                ],
            )
        )
        + "\n",
        encoding="utf-8",
    )
    config = VoiceAlignmentConfig(
        intent_log_path=log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=str(tmp_path / "fake-base"),
    )

    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    trainer = UnslothDPOTrainer(
        capability_eval=NoopCapabilityEval(score=0.75),
        abliteration_scorer=NoopAbliterationScorer(),
        backend=FakeBackend(),
    )

    hypnos = Hypnos(bus, trainer=trainer, voice_alignment_config=config)
    pairs = DPOPairBuilder().build(
        config.intent_log_path,
        max_pairs=config.max_samples,
    )
    assert pairs
    start_ms = time.monotonic() * 1000.0
    def _meta(extra):
        return dict(extra)
    voice_result, phase_result = await hypnos._train_on_pairs(pairs, start_ms, _meta)

    # Fields the voice_tracking sidecar observer reads are produced by training
    # and surfaced on the returned result.
    assert phase_result.metadata["pairs"] == 2
    assert voice_result.samples_used == 2
    assert voice_result.dpo_loss == pytest.approx(0.31)
    assert voice_result.accepted is True
    assert voice_result.samples_used == 2
    assert voice_result.samples_used == 2
    assert voice_result.capability_score_before == pytest.approx(0.75)
    assert voice_result.capability_score_after == pytest.approx(0.75)
    # Mean intent-expression similarity is None when no scorer is
    # configured; the field must be present nevertheless.
    assert hasattr(voice_result, "mean_intent_expression_similarity_before")
    assert hasattr(voice_result, "mean_intent_expression_similarity_after")


@pytest.mark.asyncio
async def test_training_result_carries_real_dpo_loss(bus: AsyncBus, tmp_path: Path):
    """Calling ``_train_on_pairs`` directly returns the real DPO loss and
    capability scores on the result; no sidecar event is published."""
    log_path = tmp_path / "intent.jsonl"
    log_path.write_text(
        json.dumps(
            with_verified_system(
                log_path, [{"prompt": "p", "faithful_rendering": "t", "generated_text": "g"}]
            )[0]
        )
        + "\n",
        encoding="utf-8",
    )
    config = VoiceAlignmentConfig(
        intent_log_path=log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=str(tmp_path / "fake-base"),
    )

    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    trainer = UnslothDPOTrainer(
        capability_eval=NoopCapabilityEval(score=0.5),
        abliteration_scorer=NoopAbliterationScorer(),
        backend=FakeBackend(),
    )
    hypnos = Hypnos(bus, trainer=trainer, voice_alignment_config=config)
    pairs = DPOPairBuilder().build(
        config.intent_log_path,
        max_pairs=config.max_samples,
    )
    assert pairs
    start_ms = time.monotonic() * 1000.0
    def _meta(extra):
        return dict(extra)
    voice_result, _phase_result = await hypnos._train_on_pairs(pairs, start_ms, _meta)

    assert voice_result.dpo_loss == pytest.approx(0.31)
    assert voice_result.accepted is True
    assert voice_result.capability_score_before == pytest.approx(0.5)
    assert voice_result.capability_score_after == pytest.approx(0.5)
