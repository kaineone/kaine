# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Real-path tests for VoiceAlignmentDivergenceObserver against Hypnos."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.evaluation.observers.voice_alignment_divergence_observer import (
    VoiceAlignmentDivergenceObserver,
)
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


class FakeSink:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def write(self, row: dict) -> None:
        self.rows.append(row)


def _intent_log(tmp_path: Path) -> Path:
    log_path = tmp_path / "intent.jsonl"
    log_path.write_text(
        json.dumps({"prompt": "p", "faithful_rendering": "t", "generated_text": "g"})
        + "\n",
        encoding="utf-8",
    )
    return log_path


def _build_hypnos(bus: AsyncBus, tmp_path: Path, *, enabled: bool):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    config = VoiceAlignmentConfig(
        intent_log_path=_intent_log(tmp_path),
        adapter_output_dir=tmp_path / "adapters",
        enabled=enabled,
        base_model_path=str(tmp_path / "fake-base"),
    )
    trainer = UnslothDPOTrainer(
        capability_eval=NoopCapabilityEval(score=0.5),
        abliteration_scorer=NoopAbliterationScorer(),
        backend=FakeBackend(),
    )
    return Hypnos(bus, trainer=trainer, voice_alignment_config=config)


def _voice_alignment_phase(payload: dict):
    """Locate the voice_alignment phase result in a sleep summary/payload."""
    return next(p for p in payload["phases"] if p["phase"] == "voice_alignment")


@pytest.mark.asyncio
async def test_observer_records_real_sleep_summary(bus: AsyncBus, tmp_path: Path):
    """The consolidation-divergence metric is emitted unconditionally even
    though the default preference_source="none" skips training."""
    hypnos = _build_hypnos(bus, tmp_path, enabled=True)
    await hypnos.enter_sleep()

    entries = await bus.read("hypnos.out", count=10)
    completed = [
        (entry_id, event)
        for entry_id, event in entries
        if event.type == "hypnos.sleep.completed"
    ]
    assert len(completed) == 1
    entry_id, event = completed[0]

    # The unconditional divergence metric is present in the voice_alignment
    # phase metadata, not as a top-level summary key.
    payload = event.payload
    phase = _voice_alignment_phase(payload)
    assert "consolidation_divergence" in phase["metadata"]
    cd = phase["metadata"]["consolidation_divergence"]
    assert cd["records_scanned"] == 1
    assert cd["usable_pairs"] == 1
    assert cd["divergence_rate"] == 1.0

    # Training did not run, so there is no training-outcome row to record.
    sink = FakeSink()
    observer = VoiceAlignmentDivergenceObserver(bus, sink)
    await observer.handle("hypnos.out", entry_id, event)

    assert sink.rows == []
    assert not any("/home/" in str(v) for v in payload.values())


@pytest.mark.asyncio
async def test_observer_skips_disabled_voice_alignment(bus: AsyncBus, tmp_path: Path):
    hypnos = _build_hypnos(bus, tmp_path, enabled=False)
    await hypnos.enter_sleep()

    entries = await bus.read("hypnos.out", count=10)
    completed = [
        (entry_id, event)
        for entry_id, event in entries
        if event.type == "hypnos.sleep.completed"
    ]
    assert len(completed) == 1
    entry_id, event = completed[0]

    sink = FakeSink()
    observer = VoiceAlignmentDivergenceObserver(bus, sink)
    await observer.handle("hypnos.out", entry_id, event)

    assert sink.rows == []
