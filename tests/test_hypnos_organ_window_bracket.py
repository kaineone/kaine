# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Hypnos brackets the trainer call with the on-device organ window.

When an organ_window_runner is injected, the voice-alignment phase runs the
trainer THROUGH it (unload→train→reload) and surfaces the window outcome in the
phase metadata. A failed window still completes the sleep cycle, and the
two-key safety gate is unchanged (the runner only runs after both gates open).
"""
from __future__ import annotations

import json

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos import Hypnos, TrainingResult, VoiceAlignmentConfig
from kaine.modules.hypnos.organ_window import OrganWindowResult
from kaine.modules.hypnos.voice_alignment import OPERATOR_APPROVED_ENV


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class _RecordingTrainer:
    def __init__(self) -> None:
        self.calls = 0

    async def train(self, pairs, config):
        self.calls += 1
        return TrainingResult(
            accepted=True,
            adapter_path=None,
            capability_loss=0.0,
            reason="trainer fired",
            samples_used=len(pairs),
        )


def _hypnos(bus, tmp_path, *, trainer, runner):
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
    )
    return Hypnos(
        bus,
        trainer=trainer,
        voice_alignment_config=config,
        organ_window_runner=runner,
    )


@pytest.mark.asyncio
async def test_runner_brackets_the_trainer_call(bus, tmp_path, monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    trainer = _RecordingTrainer()
    seen: list = []

    async def runner(train_thunk):
        seen.append("runner")
        result = await train_thunk()  # the bracket runs the real trainer
        return result, OrganWindowResult(bracketed=True, organ_restored=True)

    hypnos = _hypnos(bus, tmp_path, trainer=trainer, runner=runner)
    summary = await hypnos.enter_sleep()

    assert seen == ["runner"]  # training went THROUGH the window
    assert trainer.calls == 1
    voice = summary["voice_alignment"]
    assert voice["accepted"] is True
    # Window outcome surfaced in the voice_alignment phase metadata.
    phases = {p["phase"]: p for p in summary["phases"]}
    meta = phases["voice_alignment"]["metadata"]
    assert meta["organ_window_bracketed"] is True
    assert meta["organ_restored"] is True


@pytest.mark.asyncio
async def test_failed_window_completes_other_sleep_phases(bus, tmp_path, monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    trainer = _RecordingTrainer()

    async def runner(train_thunk):
        # Training crashed inside the window; the bracket reloaded the organ.
        return None, OrganWindowResult(
            bracketed=True, organ_restored=True, error="RuntimeError: boom"
        )

    hypnos = _hypnos(bus, tmp_path, trainer=trainer, runner=runner)
    summary = await hypnos.enter_sleep()

    # The other four sleep phases still completed (sleep is not crashed).
    phase_names = [p["phase"] for p in summary["phases"]]
    assert "voice_alignment" in phase_names
    assert len(phase_names) == 5  # all phases present
    non_voice = [p for p in summary["phases"] if p["phase"] != "voice_alignment"]
    assert all(p["success"] for p in non_voice)
    # The voice phase reports the failure but the cycle produced a summary.
    voice = summary["voice_alignment"]
    assert voice["accepted"] is False
    assert "organ window" in voice["reason"]


@pytest.mark.asyncio
async def test_gate_blocks_runner_when_not_approved(bus, tmp_path, monkeypatch):
    """The two-key gate is unchanged: no approval → runner never runs."""
    monkeypatch.delenv(OPERATOR_APPROVED_ENV, raising=False)
    trainer = _RecordingTrainer()
    ran = []

    async def runner(train_thunk):
        ran.append(1)
        return await train_thunk(), OrganWindowResult(bracketed=True, organ_restored=True)

    hypnos = _hypnos(bus, tmp_path, trainer=trainer, runner=runner)
    summary = await hypnos.enter_sleep()

    assert ran == []  # gate blocked before the window
    assert trainer.calls == 0
    assert "operator approval not granted" in summary["voice_alignment"]["reason"]
