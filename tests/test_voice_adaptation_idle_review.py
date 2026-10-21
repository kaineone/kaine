# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Review tests for sleep index advancement and retired-key warnings."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from kaine.boot.factories.sleep import make_sleep
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.lifecycle.fork_merge_gate import assess_fork
from kaine.modules.language import (
    FakeChatClient,
    IntentExpressionLog,
    Language,
)
from kaine.modules.sleep.module import Sleep
from kaine.modules.sleep.voice_alignment import (
    FakeTrainer,
    VoiceAlignmentConfig,
)
from tests._fakes import wait_for


class _FakeEpisodicMemory:
    async def consolidate_now(self) -> int:
        return 0

    async def downscale(self, protect=()):
        return {
            "n_new": 0,
            "factor": 1.0,
            "protected": len(list(protect)),
            "total_before": 0.0,
            "total_after": 0.0,
            "silent": 0,
        }

    async def replay_now(self) -> list:
        return []


class _FakeAffect:
    async def affective_reset(self) -> None:
        return None


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _make_sleep(
    bus: AsyncBus,
    tmp_path: Path,
    *,
    intent_records: list[dict] | None = None,
    enabled: bool = True,
    trainer=None,
) -> Sleep:
    log_path = tmp_path / "intent.jsonl"
    if intent_records is not None:
        _write_jsonl(log_path, intent_records)
    config = VoiceAlignmentConfig(
        intent_log_path=log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=enabled,
        preference_source="none",
    )
    return Sleep(
        bus,
        episodic_memory=_FakeEpisodicMemory(),
        affect=_FakeAffect(),
        trainer=trainer or FakeTrainer(),
        voice_alignment_config=config,
    )


def _make_language(bus: AsyncBus, tmp_path: Path, responses=None) -> Language:
    return Language(
        bus,
        chat_client=FakeChatClient(responses=responses),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )


@pytest.mark.asyncio
async def test_enter_sleep_advances_and_publishes_started_index(bus, tmp_path):
    sleep = _make_sleep(bus, tmp_path, intent_records=[], enabled=False)
    await sleep.initialize()
    try:

        await sleep.enter_sleep()
        await sleep.enter_sleep()

        entries = await bus.read("sleep.out", count=50)
        started = [e for _, e in entries if e.type == "sleep.sleep.started"]
        audits = [e for _, e in entries if e.type == "sleep.ignition_audit"]
        assert [e.payload["sleep_index"] for e in started] == [1, 2]
        assert [e.payload["sleep_index"] for e in audits] == [1, 2]
    finally:
        await sleep.shutdown()


@pytest.mark.asyncio
async def test_language_learns_index_even_if_ignition_audit_raises(bus, tmp_path):
    sleep = _make_sleep(bus, tmp_path, intent_records=[], enabled=False)
    language = _make_language(bus, tmp_path)
    await sleep.initialize()
    await language.initialize()
    try:

        async def _ignition_audit(self, since=None):
            raise RuntimeError("audit failure")

        sleep._run_ignition_audit = _ignition_audit

        await sleep.enter_sleep()
        await wait_for(lambda: language._sleep_index == 1, timeout_s=2.0)
    finally:
        await sleep.shutdown()
        await language.shutdown()


@pytest.mark.asyncio
async def test_make_sleep_warns_on_retired_keys(bus, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="kaine")

    sleep = make_sleep(bus, {"consolidation_embedder_enabled": True})
    await sleep.initialize()
    await sleep.shutdown()
    assert any(
        "consolidation_embedder_enabled" in r.message and "retired" in r.message
        for r in caplog.records
    )

    caplog.clear()
    sleep2 = make_sleep(
        bus,
        {
            "voice_alignment": {
                "enabled": False,
                "consolidation_divergence_rate_threshold": 0.5,
                "consolidation_divergence_magnitude_threshold": 0.25,
            }
        },
    )
    await sleep2.initialize()
    await sleep2.shutdown()
    warnings = [r.message for r in caplog.records if "retired" in r.message]
    assert any("consolidation_divergence_rate_threshold" in m for m in warnings)
    assert any("consolidation_divergence_magnitude_threshold" in m for m in warnings)

    caplog.clear()
    sleep3 = make_sleep(bus, {})
    await sleep3.initialize()
    await sleep3.shutdown()
    assert not any("retired" in r.message for r in caplog.records)


def test_assess_fork_re_roots_relative_voice_paths(tmp_path):
    root = tmp_path / "fork"
    root.mkdir()
    config = {"language": {"intent_log_path": "state/language/custom_intent.jsonl"}}
    log_path = root / "language" / "custom_intent.jsonl"
    _write_jsonl(log_path, [{"generated_text": "hello"}])

    with_config = assess_fork(fork_state_root=root, config=config)
    assert with_config.signals["voice_has_spoken"] is True
    assert with_config.diverged is True

    without_config = assess_fork(fork_state_root=root)
    assert without_config.signals["voice_has_spoken"] is False
    assert without_config.diverged is False

    explicit_none = assess_fork(fork_state_root=root, config=None)
    assert explicit_none.diverged == without_config.diverged
    assert explicit_none.signals == without_config.signals


def test_assess_fork_uses_absolute_path_as_given(tmp_path):
    root = tmp_path / "fork"
    root.mkdir()
    absolute_log = tmp_path / "absolute_intent.jsonl"
    _write_jsonl(absolute_log, [{"generated_text": "hello"}])
    config = {"language": {"intent_log_path": str(absolute_log)}}

    result = assess_fork(fork_state_root=root, config=config)
    assert result.signals["voice_has_spoken"] is True
    assert result.diverged is True
