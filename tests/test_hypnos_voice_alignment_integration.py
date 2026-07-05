# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""End-to-end Hypnos voice-alignment integration.

Exercises the full Hypnos.enter_sleep() path with the real
UnslothDPOTrainer wired against a FakeBackend. Asserts that the
hypnos.sleep.completed payload's top-level keys (the ones the
evaluation sidecar's voice_tracking observer consumes) are
populated end-to-end.
"""
from __future__ import annotations

import json
import sys
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
from kaine.modules.hypnos.voice_alignment import OPERATOR_APPROVED_ENV


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
async def test_end_to_end_publishes_top_level_voice_tracking_fields(
    bus: AsyncBus, tmp_path: Path,
):
    log_path = tmp_path / "intent.jsonl"
    log_path.write_text(
        "\n".join(
            json.dumps({"prompt": f"p{i}", "faithful_rendering": f"t{i}", "generated_text": f"g{i}"})
            for i in range(2)
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
    summary = await hypnos.enter_sleep()

    # Top-level fields the voice_tracking sidecar observer reads from
    # the hypnos.sleep.completed payload — none should be missing.
    assert "pairs_processed" in summary
    assert summary["pairs_processed"] == 2
    assert "pairs_above_threshold" in summary
    assert summary["pairs_above_threshold"] == 2
    assert summary["dpo_loss"] == pytest.approx(0.31)
    assert summary["adapter_accepted"] is True
    assert summary["capability_score_before"] == pytest.approx(0.75)
    assert summary["capability_score_after"] == pytest.approx(0.75)
    # Mean intent-expression similarity is None when no scorer is
    # configured; the field must be present nevertheless.
    assert "mean_intent_expression_similarity_before" in summary
    assert "mean_intent_expression_similarity_after" in summary


@pytest.mark.asyncio
async def test_sidecar_event_carries_real_dpo_loss(bus: AsyncBus, tmp_path: Path):
    """Sidecar reads hypnos.sleep.completed via the bus — verify the
    actual published event payload (not just the in-process summary)
    carries the new fields."""
    log_path = tmp_path / "intent.jsonl"
    log_path.write_text(
        json.dumps({"prompt": "p", "faithful_rendering": "t", "generated_text": "g"})
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
    await hypnos.enter_sleep()

    # Drain the hypnos stream. AsyncBus.read returns [(entry_id, Event)].
    entries = await bus.read("hypnos.out", count=10)
    payloads = [
        event.payload
        for _entry_id, event in entries
        if event.type == "hypnos.sleep.completed"
    ]
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["dpo_loss"] == pytest.approx(0.31)
    assert payload["adapter_accepted"] is True
    assert payload["capability_score_before"] == pytest.approx(0.5)
    assert payload["capability_score_after"] == pytest.approx(0.5)
