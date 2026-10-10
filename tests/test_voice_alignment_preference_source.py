# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the preference_source gate (task 0.7)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kaine.boot.errors import VoiceAlignmentConfigError
from kaine.boot.factories.hypnos import voice_alignment_config_from_section
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos import Hypnos, TrainingResult
from kaine.modules.hypnos.voice_alignment import (
    OPERATOR_APPROVED_ENV,
    PREFERENCE_SOURCES,
    DPOPairBuilder,
)
from tests.voice_prompt_support import with_verified_system


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class _RecordingTrainer:
    def __init__(self) -> None:
        self.calls: list[list] = []

    async def train(self, pairs, config):
        self.calls.append(list(pairs))
        return TrainingResult(
            accepted=True,
            adapter_path=None,
            capability_loss=0.0,
            reason="trainer fired",
            samples_used=len(pairs),
        )


def _section(tmp_path: Path, **overrides):
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
    section = {
        "intent_log_path": str(log_path),
        "adapter_output_dir": str(tmp_path / "adapters"),
        "enabled": True,
    }
    section.update(overrides)
    return section


def _voice_alignment_phase(payload: dict):
    """Locate the voice_alignment phase result in a sleep summary/payload."""
    return next(p for p in payload["phases"] if p["phase"] == "voice_alignment")


def test_factory_default_preference_source_is_none(tmp_path: Path):
    cfg = voice_alignment_config_from_section(_section(tmp_path))
    assert cfg is not None
    assert cfg.preference_source == "none"
    assert cfg.preference_source in PREFERENCE_SOURCES


def test_factory_rejects_unknown_preference_source(tmp_path: Path):
    with pytest.raises(VoiceAlignmentConfigError) as excinfo:
        voice_alignment_config_from_section(
            _section(tmp_path, preference_source="faithful_rendering")
        )
    msg = str(excinfo.value)
    assert "preference_source" in msg
    assert "faithful_rendering" in msg
    assert "none" in msg


def test_factory_rejects_non_string_preference_source(tmp_path: Path):
    with pytest.raises(VoiceAlignmentConfigError) as excinfo:
        voice_alignment_config_from_section(_section(tmp_path, preference_source=True))
    msg = str(excinfo.value)
    assert "preference_source" in msg
    assert "must be one of" in msg
    assert "bool" in msg


@pytest.mark.asyncio
async def test_preference_source_none_skips_training_but_emits_divergence(
    bus: AsyncBus, tmp_path: Path, monkeypatch,
):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    trainer = _RecordingTrainer()
    cfg = voice_alignment_config_from_section(_section(tmp_path))
    hypnos = Hypnos(bus, trainer=trainer, voice_alignment_config=cfg)
    summary = await hypnos.enter_sleep()

    assert trainer.calls == []
    voice = summary["voice_alignment"]
    assert "no validated preference source" in voice["reason"]
    assert voice["accepted"] is False
    assert voice["samples_used"] == 0
    assert summary["dpo_loss"] is None
    assert summary["adapter_accepted"] is False
    assert summary["pairs_processed"] == 0

    # Divergence metric is still emitted unconditionally, now inside the
    # voice_alignment phase metadata.
    phase = _voice_alignment_phase(summary)
    assert "consolidation_divergence" in phase["metadata"]
    cd = phase["metadata"]["consolidation_divergence"]
    assert cd["records_scanned"] == 1
    assert cd["usable_pairs"] == 1
    assert cd["divergence_rate"] == 1.0

    # The bus event also carries the metric inside the phase metadata.
    entries = await bus.read("hypnos.out", count=10)
    payloads = [
        event.payload
        for _entry_id, event in entries
        if event.type == "hypnos.sleep.completed"
    ]
    assert len(payloads) == 1
    phase = _voice_alignment_phase(payloads[0])
    assert "consolidation_divergence" in phase["metadata"]
    cd = phase["metadata"]["consolidation_divergence"]
    assert cd["usable_pairs"] == 1


@pytest.mark.asyncio
async def test_train_on_pairs_calls_trainer_with_given_pairs(
    bus: AsyncBus, tmp_path: Path,
):
    cfg = voice_alignment_config_from_section(_section(tmp_path))
    trainer = _RecordingTrainer()
    hypnos = Hypnos(bus, trainer=trainer, voice_alignment_config=cfg)

    pairs = DPOPairBuilder().build(cfg.intent_log_path, max_pairs=cfg.max_samples)
    assert pairs, "the fixture intent log must yield at least one pair"
    start_ms = time.monotonic() * 1000.0
    def _meta(extra):
        return dict(extra)
    voice_result, phase_result = await hypnos._train_on_pairs(pairs, start_ms, _meta)

    assert len(trainer.calls) == 1
    # The same pairs, each now carrying its verified system prompt.
    assert [p.prompt for p in trainer.calls[0]] == [p.prompt for p in pairs]
    assert all(p.system == "I am a test persona." for p in trainer.calls[0])
    assert voice_result.accepted is True
    assert voice_result.samples_used == len(pairs)
    assert phase_result.success is True
    assert phase_result.metadata["pairs"] == len(pairs)


def test_config_itself_refuses_an_unknown_source(tmp_path):
    """A config built directly, not through the boot factory, cannot name an
    unimplemented source either."""
    from kaine.modules.hypnos.voice_alignment import VoiceAlignmentConfig

    with pytest.raises(ValueError, match="unknown preference_source"):
        VoiceAlignmentConfig(
            intent_log_path=tmp_path / "log.jsonl",
            adapter_output_dir=tmp_path / "adapters",
            preference_source="faithful_rendering",
        )


def test_corpus_ceiling_must_be_a_non_negative_number(tmp_path):
    from kaine.boot.errors import VoiceAlignmentConfigError
    from kaine.boot.factories.hypnos import voice_alignment_config_from_section
    from kaine.modules.hypnos.voice_alignment import VoiceAlignmentConfig

    with pytest.raises(ValueError, match="corpus_ceiling_gb"):
        VoiceAlignmentConfig(
            intent_log_path=tmp_path / "log.jsonl",
            adapter_output_dir=tmp_path / "adapters",
            corpus_ceiling_gb=-1.0,
        )
    for bad in ("lots", -2):
        with pytest.raises(VoiceAlignmentConfigError, match="corpus_ceiling_gb"):
            voice_alignment_config_from_section({"corpus_ceiling_gb": bad})
