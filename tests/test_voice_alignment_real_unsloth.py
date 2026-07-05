# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator bring-up test for the real voice-alignment training stack.

Gated behind `KAINE_HAS_UNSLOTH_TRAINING=1`. Skipped by default.

Runs one DPO step against a tiny base model the operator has already
downloaded (path supplied via `KAINE_VOICE_ALIGNMENT_TEST_BASE_MODEL`)
to verify the [training] extras install end-to-end and that an
adapter directory survives the promotion step.

Do NOT enable in CI — it requires CUDA, several GB of weights, and a
real GPU. This is the operator's "did I install this correctly?"
canary.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("KAINE_HAS_UNSLOTH_TRAINING") != "1",
    reason=(
        "set KAINE_HAS_UNSLOTH_TRAINING=1 and "
        "KAINE_VOICE_ALIGNMENT_TEST_BASE_MODEL=<path to HF weights> to run"
    ),
)


@pytest.mark.asyncio
async def test_real_unsloth_one_dpo_step(tmp_path: Path):
    base_model = os.environ.get("KAINE_VOICE_ALIGNMENT_TEST_BASE_MODEL")
    if not base_model:
        pytest.skip(
            "set KAINE_VOICE_ALIGNMENT_TEST_BASE_MODEL to a HF-format "
            "model directory (e.g. TinyLlama 1.1B 4-bit)"
        )

    from kaine.modules.hypnos.capability_eval import NoopCapabilityEval
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer
    from kaine.modules.hypnos.voice_alignment import (
        DPOPair,
        VoiceAlignmentConfig,
    )

    cfg = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=base_model,
        max_samples=2,
        lora_rank=4,
        learning_rate=5e-5,
        dpo_beta=0.1,
        seed=42,
        training_device=os.environ.get(
            "KAINE_VOICE_ALIGNMENT_TEST_DEVICE", "cuda:0"
        ),
    )
    pairs = [
        DPOPair(
            prompt="Question: What is the capital of France?",
            chosen=" The capital of France is Paris.",
            rejected=" I don't know about that.",
        ),
        DPOPair(
            prompt="Question: What is 2+2?",
            chosen=" 2+2 is 4.",
            rejected=" I cannot answer.",
        ),
    ]
    trainer = UnslothDPOTrainer(
        # Use a Noop eval so the test doesn't get blocked on the
        # capability-loss veto — we only care that the DPO step ran.
        capability_eval=NoopCapabilityEval(score=1.0),
    )
    result = await trainer.train(pairs, cfg)
    assert result.accepted is True, f"trainer rejected: {result.reason}"
    assert result.adapter_path is not None
    assert result.adapter_path.exists()
    assert result.dpo_loss is not None
