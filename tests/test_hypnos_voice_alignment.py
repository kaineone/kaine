# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
from pathlib import Path

import pytest

from kaine.modules.hypnos.voice_alignment import (
    DPOPair,
    DPOPairBuilder,
    FakeTrainer,
    Trainer,
    TrainingResult,
    UnslothDPOTrainer,
    VoiceAlignmentConfig,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_builder_missing_file_returns_empty(tmp_path: Path):
    b = DPOPairBuilder()
    pairs = b.build(tmp_path / "missing.jsonl", max_pairs=10)
    assert pairs == []


def test_builder_yields_pair_per_qualifying_record(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    _write_jsonl(p, [
        {"prompt": "a", "faithful_rendering": "truth-1", "generated_text": "out-1"},
        {"prompt": "b", "faithful_rendering": "truth-2", "generated_text": "out-2"},
        {"prompt": "c", "faithful_rendering": "truth-3", "generated_text": ""},  # no out
        {"prompt": "d", "faithful_rendering": "", "generated_text": "out-4"},   # no truth
        {"prompt": "e", "faithful_rendering": "same", "generated_text": "same"},# no signal
    ])
    pairs = DPOPairBuilder().build(p, max_pairs=10)
    assert len(pairs) == 2
    assert pairs[0].chosen == "truth-1"
    assert pairs[0].rejected == "out-1"


def test_builder_max_pairs_caps(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    _write_jsonl(p, [
        {"prompt": str(i), "faithful_rendering": f"t{i}", "generated_text": f"g{i}"}
        for i in range(10)
    ])
    pairs = DPOPairBuilder().build(p, max_pairs=3)
    assert len(pairs) == 3


def test_builder_skips_malformed_lines(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"prompt": "a", "faithful_rendering": "t", "generated_text": "g"}\n'
        "not-json\n"
        '{"prompt": "b", "faithful_rendering": "t2", "generated_text": "g2"}\n',
        encoding="utf-8",
    )
    pairs = DPOPairBuilder().build(p, max_pairs=10)
    assert len(pairs) == 2


def test_fake_satisfies_trainer_protocol():
    assert isinstance(FakeTrainer(), Trainer)


@pytest.mark.asyncio
async def test_fake_rejects_by_default(tmp_path: Path):
    trainer = FakeTrainer()
    cfg = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "log.jsonl",
        adapter_output_dir=tmp_path / "adapters",
    )
    result = await trainer.train([DPOPair("p", "c", "r")], cfg)
    assert result.accepted is False
    assert result.adapter_path is None
    assert "no training backend" in result.reason


@pytest.mark.asyncio
async def test_fake_can_accept_for_capability_test(tmp_path: Path):
    trainer = FakeTrainer(
        accept=True,
        capability_loss=0.01,
        reason="ok",
    )
    cfg = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "log.jsonl",
        adapter_output_dir=tmp_path / "adapters",
    )
    result = await trainer.train([DPOPair("p", "c", "r")], cfg)
    assert result.accepted is True
    assert result.adapter_path is not None
    assert result.adapter_path.exists()


@pytest.mark.asyncio
async def test_unsloth_trainer_returns_clear_error_when_deps_missing(tmp_path: Path, monkeypatch):
    import sys
    # Force the unsloth import path to fail.
    monkeypatch.setitem(sys.modules, "unsloth", None)
    trainer = UnslothDPOTrainer()
    cfg = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "log.jsonl",
        adapter_output_dir=tmp_path / "adapters",
    )
    result = await trainer.train([DPOPair("p", "c", "r")], cfg)
    assert result.accepted is False
    assert "unsloth" in result.reason.lower()


def test_voice_alignment_config_defaults(tmp_path: Path):
    cfg = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "log.jsonl",
        adapter_output_dir=tmp_path / "adapters",
    )
    assert cfg.lora_rank == 8
    assert cfg.dpo_beta == 0.1
    assert cfg.capability_loss_threshold == 0.05
