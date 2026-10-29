# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the content-free individuation block in runtime.json."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from kaine.cycle.__main__ import _individuation_runtime_reading, _write_runtime_state
from kaine.cycle.individuation_runtime import IndividuationConfig, build_runtime
from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    Ledger,
    ProbeSample,
    ReferenceDoc,
    battery_digest_of,
    save_ledger,
    save_reference,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)

    async def last_entry_id(self, stream: str) -> str:
        return "0-0"

    async def read_entries(
        self, stream: str, last_id: str, count: int, block_ms: int
    ) -> tuple[list[tuple[str, Any]], str | None]:
        await asyncio.sleep(0.005)
        return ([], None)


class _FakeLanguage:
    def __init__(self) -> None:
        self.probe_temperature: float | None = None
        self._cond = {
            "model_id": "m",
            "temperature": 0.5,
            "think": False,
            "persona_digest": "abcd1234abcd1234",
        }

    def set_probe_temperature(self, value: float) -> None:
        self.probe_temperature = value

    def probe_self_model(self) -> dict:
        return {
            "values": ["val"],
            "behavioral_norms": ["norm"],
            "situation_facts": [],
        }

    def probe_request(self, about: str, *, seed: int, max_tokens: int, self_model: dict) -> Any:
        return MagicMock()

    def is_idle(self, quiet_s: float) -> bool:
        return True

    def probe_conditions(self) -> dict:
        return dict(self._cond)


class _FakeEmbedder:
    kind = "sentence_transformers"
    model_id = "e"
    latent_dim = 3

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self.latent_dim


class _FakeEnsureFact:
    async def __call__(self, fact: str, *, replaces: tuple[str, ...] = ()) -> bool:
        return True


def _build_runtime(tmp_path: Path) -> Any:
    config = IndividuationConfig.from_dict({"enabled": True})
    return build_runtime(
        config=config,
        battery=["q1", "q2"],
        language=_FakeLanguage(),
        ensure_fact=_FakeEnsureFact(),
        embedder=_FakeEmbedder(),
        adapter_output_dir=None,
        per_request_adapter=False,
        state_root=tmp_path / "ind",
        clock_now=lambda: 0.0,
        paused_seconds=lambda: 0.0,
        tick_index=lambda: 0,
        is_paused=lambda: False,
        organ_unloaded=lambda: False,
        sleeping=None,
        born_at=lambda: None,
        is_developing=lambda: False,
        bus=_FakeBus(),
        notify=None,
        entity_name="test",
    )


def _make_reference(paths: IndividuationPaths, reference_id: str) -> ReferenceDoc:
    samples = tuple(
        tuple(
            ProbeSample(
                text=f"p{i}s{j}",
                seed=j,
                finish_reason="stop",
                completion_tokens=1,
            )
            for j in range(2)
        )
        for i in range(2)
    )
    return ReferenceDoc(
        reference_id=reference_id,
        reference_kind="maturation",
        captured_at="2026-01-01T00:00:00+00:00",
        born_at=None,
        battery=tuple(["q1", "q2"]),
        battery_digest=battery_digest_of(tuple(["q1", "q2"])),
        conditions={},
        conditioning={},
        samples=samples,
    )


@pytest.fixture
def encrypted(tmp_path: Path, monkeypatch):
    key = os.urandom(32).hex()
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    previous = StateEncryptor(CryptoConfig(enabled=False))
    try:
        enc = StateEncryptor(CryptoConfig(enabled=True))
        set_state_encryptor(enc)
        yield tmp_path
    finally:
        set_state_encryptor(previous)
        monkeypatch.delenv("KAINE_STATE_KEY", raising=False)


def test_individuation_runtime_reading_with_maturation_reference(encrypted: Path):
    runtime = _build_runtime(encrypted)
    ref = _make_reference(runtime.paths, "ref-1")
    save_reference(runtime.paths, ref)
    save_ledger(
        runtime.paths,
        Ledger(
            reference_id="ref-1",
            looks_completed=0,
            alpha_spent=0.0,
            lived_seconds=0.0,
            lived_ticks=0,
        ),
    )
    runtime.scheduler._refresh_state()
    # The reference is ciphertext on disk, as in a real seed.
    with pytest.raises(ValueError):
        json.loads(runtime.paths.reference.read_bytes())

    reading = _individuation_runtime_reading(runtime)
    assert reading is not None
    assert set(reading) == {"reference_kind", "reference_complete"}
    assert reading["reference_kind"] == "maturation"
    assert reading["reference_complete"] is True


def test_individuation_runtime_reading_without_scheduler():
    assert _individuation_runtime_reading(None) is None


def test_individuation_runtime_reading_with_missing_ledger(encrypted: Path):
    runtime = _build_runtime(encrypted)
    ref = _make_reference(runtime.paths, "ref-1")
    save_reference(runtime.paths, ref)
    runtime.scheduler._refresh_state()
    # No ledger on disk.
    reading = _individuation_runtime_reading(runtime)
    assert reading is not None
    assert reading["reference_kind"] == "maturation"
    assert reading["reference_complete"] is False


@pytest.mark.asyncio
async def test_write_runtime_state_includes_individuation_block(encrypted: Path, monkeypatch):
    runtime_path = encrypted / "runtime.json"
    monkeypatch.setattr("kaine.cycle.__main__.RUNTIME_PATH", runtime_path)

    runtime = _build_runtime(encrypted)
    ref = _make_reference(runtime.paths, "ref-1")
    save_reference(runtime.paths, ref)
    save_ledger(
        runtime.paths,
        Ledger(
            reference_id="ref-1",
            looks_completed=0,
            alpha_spent=0.0,
            lived_seconds=0.0,
            lived_ticks=0,
        ),
    )
    runtime.scheduler._refresh_state()

    cycle = MagicMock()
    cycle.tick_index = 0
    cycle.processing_rate_hz = 1.0
    cycle.experiential_rate_hz = 1.0
    cycle.is_paused = False
    cycle.time_scale = 1.0
    cycle.deterministic = False
    cycle.pacing_stats = {}

    registry = MagicMock()
    registry.all_modules.return_value = []

    await _write_runtime_state(
        cycle, registry, individuation=_individuation_runtime_reading(runtime)
    )

    raw = json.loads(runtime_path.read_text())
    assert raw["individuation"] == {
        "reference_kind": "maturation",
        "reference_complete": True,
    }


@pytest.mark.asyncio
async def test_write_runtime_state_omits_individuation_without_block(tmp_path: Path, monkeypatch):
    runtime_path = tmp_path / "runtime.json"
    monkeypatch.setattr("kaine.cycle.__main__.RUNTIME_PATH", runtime_path)

    cycle = MagicMock()
    cycle.tick_index = 0
    cycle.processing_rate_hz = 1.0
    cycle.experiential_rate_hz = 1.0
    cycle.is_paused = False
    cycle.time_scale = 1.0
    cycle.deterministic = False
    cycle.pacing_stats = {}

    registry = MagicMock()
    registry.all_modules.return_value = []

    await _write_runtime_state(cycle, registry, individuation=None)

    raw = json.loads(runtime_path.read_text())
    assert "individuation" not in raw
