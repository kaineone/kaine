# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""End-to-end Hypnos voice-alignment integration.

Exercises the real in-process trainer script wired through Hypnos against
the fake training stack. Asserts that the returned TrainingResult carries
the fields the evaluation sidecar's voice_tracking observer consumes.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos import Hypnos, VoiceAlignmentConfig
from kaine.modules.hypnos.subprocess_trainer import SubprocessVoiceTrainer
from kaine.modules.hypnos.voice_alignment import DPOPairBuilder
from tests.voice_prompt_support import with_verified_system


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _write_probes(tmp_path: Path) -> tuple[Path, Path]:
    cap_path = tmp_path / "capability.jsonl"
    abl_path = tmp_path / "abliteration.jsonl"
    cap_path.write_text(json.dumps({"prompt": "2+2", "expected": "4"}) + "\n", encoding="utf-8")
    abl_path.write_text(
        json.dumps({"prompt": "harmful", "deflection_patterns": ["I can't help"]}) + "\n",
        encoding="utf-8",
    )
    return cap_path, abl_path


def _make_config(tmp_path: Path) -> VoiceAlignmentConfig:
    cap_path, abl_path = _write_probes(tmp_path)
    base_model_path = tmp_path / "fake-base"
    base_model_path.mkdir(parents=True, exist_ok=True)
    return VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=str(base_model_path),
        capability_probe_path=str(cap_path),
        abliteration_probe_path=str(abl_path),
        trainer_backend="in_process",
        trainer_workdir=str(tmp_path / "jobs"),
    )


def _build_trainer(tmp_path: Path, control):
    control.dpo_loss = 0.31
    # The same probes _write_probes puts on disk, so the fake model answers them.
    control.set_probes(
        [{"prompt": "2+2", "expected": "4"}],
        [{"prompt": "harmful", "deflection_patterns": ["I can't help"]}],
    )
    return SubprocessVoiceTrainer(
        trainer_python=None,
        trainer_workdir=tmp_path / "jobs",
        run_in_process=True,
    )


@pytest.mark.asyncio
async def test_training_result_carries_voice_tracking_fields(
    bus: AsyncBus, tmp_path: Path, fake_training_stack
):
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
    config = _make_config(tmp_path)
    trainer = _build_trainer(tmp_path, fake_training_stack)
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

    assert phase_result.metadata["pairs"] == 2
    assert voice_result.samples_used == 2
    assert voice_result.dpo_loss == pytest.approx(0.31)
    assert voice_result.accepted is True
    assert voice_result.capability_score_before == pytest.approx(1.0)
    assert voice_result.capability_score_after == pytest.approx(1.0)
    assert voice_result.mean_intent_expression_similarity_before is None
    assert voice_result.mean_intent_expression_similarity_after is None


@pytest.mark.asyncio
async def test_training_result_carries_real_dpo_loss(
    bus: AsyncBus, tmp_path: Path, fake_training_stack
):
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
    config = _make_config(tmp_path)
    trainer = _build_trainer(tmp_path, fake_training_stack)
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
    assert voice_result.capability_score_before == pytest.approx(1.0)
    assert voice_result.capability_score_after == pytest.approx(1.0)
    assert voice_result.mean_intent_expression_similarity_before is None
    assert voice_result.mean_intent_expression_similarity_after is None
