# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the two-layer voice-alignment safety gate.

Both `[hypnos.voice_alignment].enabled` AND the env var
KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1 must be set or no real
training fires. Missing either condition produces a clean skip
PhaseResult rather than an error.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos import (
    Hypnos,
    Trainer,
    TrainingResult,
    VoiceAlignmentConfig,
)
from kaine.modules.hypnos.voice_alignment import OPERATOR_APPROVED_ENV


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class RecordingTrainer:
    def __init__(self) -> None:
        self.calls: list[tuple[int, VoiceAlignmentConfig]] = []

    async def train(self, pairs, config):
        self.calls.append((len(pairs), config))
        return TrainingResult(
            accepted=True,
            adapter_path=None,
            capability_loss=0.0,
            reason="trainer fired",
            samples_used=len(pairs),
        )


def _hypnos(bus, tmp_path: Path, *, enabled: bool, trainer: Trainer | None = None):
    log_path = tmp_path / "intent.jsonl"
    log_path.write_text(
        json.dumps({"prompt": "p", "faithful_rendering": "t", "generated_text": "g"})
        + "\n",
        encoding="utf-8",
    )
    config = VoiceAlignmentConfig(
        intent_log_path=log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=enabled,
    )
    return Hypnos(
        bus,
        trainer=trainer or RecordingTrainer(),
        voice_alignment_config=config,
    )


@pytest.mark.asyncio
async def test_disabled_config_skips_without_calling_trainer(bus, tmp_path, monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")  # env on, config off
    trainer = RecordingTrainer()
    hypnos = _hypnos(bus, tmp_path, enabled=False, trainer=trainer)
    summary = await hypnos.enter_sleep()
    assert trainer.calls == []
    voice = summary["voice_alignment"]
    assert "config disabled" in voice["reason"]
    # Top-level sidecar fields are present and reflect "no training".
    assert summary["dpo_loss"] is None
    assert summary["adapter_accepted"] is False
    assert summary["pairs_processed"] == 0


@pytest.mark.asyncio
async def test_missing_env_var_skips_without_calling_trainer(bus, tmp_path, monkeypatch):
    monkeypatch.delenv(OPERATOR_APPROVED_ENV, raising=False)
    trainer = RecordingTrainer()
    hypnos = _hypnos(bus, tmp_path, enabled=True, trainer=trainer)
    summary = await hypnos.enter_sleep()
    assert trainer.calls == []
    voice = summary["voice_alignment"]
    assert "operator approval not granted" in voice["reason"]
    assert OPERATOR_APPROVED_ENV in voice["reason"]


@pytest.mark.asyncio
async def test_both_gates_open_invokes_trainer(bus, tmp_path, monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    trainer = RecordingTrainer()
    hypnos = _hypnos(bus, tmp_path, enabled=True, trainer=trainer)
    summary = await hypnos.enter_sleep()
    assert len(trainer.calls) == 1
    pair_count, _config = trainer.calls[0]
    assert pair_count == 1
    voice = summary["voice_alignment"]
    assert voice["accepted"] is True


@pytest.mark.asyncio
async def test_env_var_must_be_exactly_one(bus, tmp_path, monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "true")  # truthy but not "1"
    trainer = RecordingTrainer()
    hypnos = _hypnos(bus, tmp_path, enabled=True, trainer=trainer)
    summary = await hypnos.enter_sleep()
    assert trainer.calls == []
    assert "operator approval not granted" in summary["voice_alignment"]["reason"]
