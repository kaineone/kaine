# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests that the sleep index survives restarts."""

import logging

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.lifecycle.stage import StageState, write_stage
from kaine.modules.sleep.corpus import rotate_intent_log
from kaine.modules.sleep.module import Sleep
from kaine.modules.sleep.voice_alignment import VoiceAlignmentConfig


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _voice_config(tmp_path):
    return VoiceAlignmentConfig(
        intent_log_path=tmp_path / "language" / "intent_expression.jsonl",
        adapter_output_dir=tmp_path / "adapters",
    )


def _sleep(bus, tmp_path, **kwargs):
    return Sleep(
        bus,
        voice_alignment_config=_voice_config(tmp_path),
        consolidation_divergence_path=tmp_path / "sleep" / "consolidation_divergence.json",
        consolidation_embedder=None,
        fatigue_triggered=False,
        **kwargs,
    )


def _stage_path(tmp_path):
    return tmp_path / "state" / "lifecycle" / "stage.json"


@pytest.mark.asyncio
async def test_serialize_carries_and_deserialize_restores_sleep_index(bus, tmp_path):
    sleep = _sleep(bus, tmp_path)
    sleep._sleep_count = 3

    state = sleep.serialize()
    assert state.get("sleep_index") == 3

    other = _sleep(bus, tmp_path)
    assert other._sleep_count == 0
    other.deserialize(state)
    assert other._sleep_count == 3


@pytest.mark.parametrize("bad_value", [-1, True, "3", 2.5])
def test_deserialize_ignores_malformed_sleep_index(bus, tmp_path, bad_value, caplog):
    caplog.set_level(logging.WARNING)
    sleep = _sleep(bus, tmp_path)
    sleep.deserialize({"sleep_index": bad_value})
    assert sleep._sleep_count == 0
    assert "sleep: malformed sleep_index in snapshot; keeping 0" in caplog.text


def test_deserialize_missing_sleep_index_leaves_zero(bus, tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    sleep = _sleep(bus, tmp_path)
    sleep.deserialize({})
    assert sleep._sleep_count == 0
    assert "malformed sleep_index" not in caplog.text


@pytest.mark.asyncio
async def test_initialize_restores_sleep_index_from_stage(bus, tmp_path):
    write_stage(StageState(sleep_count=4))
    sleep = _sleep(bus, tmp_path)
    await sleep.initialize()
    try:
        assert sleep._sleep_count == 4
        _, metric = await sleep._emit_consolidation_divergence()
        sleep_index = metric.get("sleep_index") if isinstance(metric, dict) else metric.sleep_index
        assert sleep_index == 5
    finally:
        await sleep.shutdown()


@pytest.mark.asyncio
async def test_deserialize_wins_over_stage(bus, tmp_path):
    sleep = _sleep(bus, tmp_path)
    sleep.deserialize({"sleep_index": 6})
    write_stage(StageState(sleep_count=4))
    await sleep.initialize()
    try:
        assert sleep._sleep_count == 6
    finally:
        await sleep.shutdown()


@pytest.mark.asyncio
async def test_stage_wins_over_deserialize(bus, tmp_path):
    write_stage(StageState(sleep_count=5))
    sleep = _sleep(bus, tmp_path)
    await sleep.initialize()
    try:
        assert sleep._sleep_count == 5
        sleep.deserialize({"sleep_index": 3})
        assert sleep._sleep_count == 5
    finally:
        await sleep.shutdown()


@pytest.mark.asyncio
async def test_initialize_leaves_zero_without_stage(bus, tmp_path):
    sleep = _sleep(bus, tmp_path)
    await sleep.initialize()
    try:
        assert sleep._sleep_count == 0
    finally:
        await sleep.shutdown()


@pytest.mark.asyncio
async def test_initialize_survives_invalid_stage_file(bus, tmp_path):
    stage_path = _stage_path(tmp_path)
    stage_path.parent.mkdir(parents=True, exist_ok=True)
    stage_path.write_text("{invalid json")
    sleep = _sleep(bus, tmp_path)
    await sleep.initialize()
    try:
        assert sleep._sleep_count == 0
    finally:
        await sleep.shutdown()


def test_rotate_intent_log_uses_sleep_index(tmp_path):
    log_path = tmp_path / "language" / "intent_expression.jsonl"
    corpus_dir = tmp_path / "corpus"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text('{"record": 1}\n')
    result = rotate_intent_log(log_path, corpus_dir, sleep_index=5)
    assert result is not None
    assert result.name.endswith("-0005.jsonl")
