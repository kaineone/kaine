# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Real-path tests for VoiceAlignmentDivergenceObserver against Hypnos."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.evaluation.observers.voice_alignment_divergence_observer import (
    VoiceAlignmentDivergenceObserver,
)
from kaine.modules.hypnos import Hypnos, VoiceAlignmentConfig
from kaine.modules.hypnos.subprocess_trainer import SubprocessVoiceTrainer
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
    yield


def _intent_log(tmp_path: Path) -> Path:
    log_path = tmp_path / "intent.jsonl"
    log_path.write_text(
        json.dumps({"prompt": "p", "faithful_rendering": "t", "generated_text": "g"})
        + "\n",
        encoding="utf-8",
    )
    return log_path


def _write_probes(tmp_path: Path) -> tuple[Path, Path]:
    cap_path = tmp_path / "capability.jsonl"
    abl_path = tmp_path / "abliteration.jsonl"
    cap_path.write_text(json.dumps({"prompt": "2+2", "expected": "4"}) + "\n", encoding="utf-8")
    abl_path.write_text(
        json.dumps({"prompt": "harmful", "deflection_patterns": ["I can't help"]}) + "\n",
        encoding="utf-8",
    )
    return cap_path, abl_path


def _build_hypnos(bus: AsyncBus, tmp_path: Path, *, enabled: bool, fake_training_stack):
    cap_path, abl_path = _write_probes(tmp_path)
    config = VoiceAlignmentConfig(
        intent_log_path=_intent_log(tmp_path),
        adapter_output_dir=tmp_path / "adapters",
        enabled=enabled,
        base_model_path=str(tmp_path / "fake-base"),
        capability_probe_path=str(cap_path),
        abliteration_probe_path=str(abl_path),
        trainer_backend="in_process",
        trainer_workdir=str(tmp_path / "jobs"),
    )
    trainer = SubprocessVoiceTrainer(
        trainer_python=None,
        trainer_workdir=tmp_path / "jobs",
        run_in_process=True,
    )
    return Hypnos(bus, trainer=trainer, voice_alignment_config=config)


def _voice_alignment_phase(payload: dict):
    return next(p for p in payload["phases"] if p["phase"] == "voice_alignment")


class FakeSink:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def write(self, row: dict) -> None:
        self.rows.append(row)


@pytest.mark.asyncio
async def test_observer_records_real_sleep_summary(bus: AsyncBus, tmp_path: Path, fake_training_stack):
    hypnos = _build_hypnos(bus, tmp_path, enabled=True, fake_training_stack=fake_training_stack)
    await hypnos.enter_sleep()

    entries = await bus.read("hypnos.out", count=10)
    completed = [
        (entry_id, event)
        for entry_id, event in entries
        if event.type == "hypnos.sleep.completed"
    ]
    assert len(completed) == 1
    entry_id, event = completed[0]

    payload = event.payload
    phase = _voice_alignment_phase(payload)
    assert "consolidation_divergence" in phase["metadata"]
    cd = phase["metadata"]["consolidation_divergence"]
    assert cd["records_scanned"] == 1
    assert cd["usable_pairs"] == 1
    assert cd["divergence_rate"] == 1.0

    sink = FakeSink()
    observer = VoiceAlignmentDivergenceObserver(bus, sink)
    await observer.handle("hypnos.out", entry_id, event)

    assert sink.rows == []
    assert not any("/home/" in str(v) for v in payload.values())


@pytest.mark.asyncio
async def test_observer_skips_disabled_voice_alignment(bus: AsyncBus, tmp_path: Path, fake_training_stack):
    hypnos = _build_hypnos(bus, tmp_path, enabled=False, fake_training_stack=fake_training_stack)
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
