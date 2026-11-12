# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.residency.voice_latency."""

from __future__ import annotations

import pytest

from kaine.residency.voice_latency import (
    PersistentMissReport,
    VoiceTurnBreakdown,
    check_persistent_misses,
    clear_voice_turn_breakdowns,
    cold_turns,
    record_voice_turn,
    voice_turn_breakdowns,
    warm_turns,
)


@pytest.fixture(autouse=True)
def _clean_breakdowns():
    """Isolate every test from module-level state."""
    clear_voice_turn_breakdowns()
    yield
    clear_voice_turn_breakdowns()


def _make(
    *,
    is_cold: bool = False,
    rung_label: str = "chatterbox",
    queue_wait_ms: float = 1.0,
    preempt_wait_ms: float = 2.0,
    load_ms: float = 0.0,
    stt_ms: float = 10.0,
    llm_first_token_ms: float = 20.0,
    tts_first_chunk_ms: float = 15.0,
) -> VoiceTurnBreakdown:
    return VoiceTurnBreakdown(
        queue_wait_ms=queue_wait_ms,
        preempt_wait_ms=preempt_wait_ms,
        load_ms=load_ms,
        stt_ms=stt_ms,
        llm_first_token_ms=llm_first_token_ms,
        tts_first_chunk_ms=tts_first_chunk_ms,
        rung_label=rung_label,
        is_cold=is_cold,
    )


# ------------------------------------------------------------------
# 1. record and snapshot
# ------------------------------------------------------------------


def test_record_and_snapshot():
    b = _make()
    returned = record_voice_turn(b)
    assert returned is b
    snap = voice_turn_breakdowns()
    assert len(snap) == 1
    assert snap[0] is b


# ------------------------------------------------------------------
# 2. warm / cold separation
# ------------------------------------------------------------------


def test_warm_cold_separation():
    record_voice_turn(_make(is_cold=False))
    record_voice_turn(_make(is_cold=False))
    record_voice_turn(_make(is_cold=True, load_ms=500.0))
    assert len(warm_turns()) == 2
    assert len(cold_turns()) == 1


# ------------------------------------------------------------------
# 3. total_ms
# ------------------------------------------------------------------


def test_total_ms():
    b = _make(
        queue_wait_ms=1.0,
        preempt_wait_ms=2.0,
        load_ms=3.0,
        stt_ms=4.0,
        llm_first_token_ms=5.0,
        tts_first_chunk_ms=6.0,
    )
    assert b.total_ms == pytest.approx(21.0)


# ------------------------------------------------------------------
# 4. as_dict
# ------------------------------------------------------------------


def test_as_dict():
    b = _make(
        queue_wait_ms=1.0,
        preempt_wait_ms=2.0,
        load_ms=3.0,
        stt_ms=4.0,
        llm_first_token_ms=5.0,
        tts_first_chunk_ms=6.0,
        rung_label="sherpa_onnx:kokoro-en",
        is_cold=True,
    )
    d = b.as_dict()
    assert d["queue_wait_ms"] == 1.0
    assert d["preempt_wait_ms"] == 2.0
    assert d["load_ms"] == 3.0
    assert d["stt_ms"] == 4.0
    assert d["llm_first_token_ms"] == 5.0
    assert d["tts_first_chunk_ms"] == 6.0
    assert d["rung_label"] == "sherpa_onnx:kokoro-en"
    assert d["is_cold"] is True
    assert d["total_ms"] == pytest.approx(21.0)
    assert "ts" in d


# ------------------------------------------------------------------
# 5. persistent miss below threshold
# ------------------------------------------------------------------


def test_persistent_miss_below_threshold():
    record_voice_turn(_make(is_cold=True, load_ms=500.0))
    record_voice_turn(_make(is_cold=True, load_ms=500.0))
    reports = check_persistent_misses(threshold=3)
    assert reports == []


# ------------------------------------------------------------------
# 6. persistent miss above threshold
# ------------------------------------------------------------------


def test_persistent_miss_above_threshold():
    for _ in range(4):
        record_voice_turn(_make(is_cold=True, load_ms=500.0))
    reports = check_persistent_misses(threshold=3)
    assert len(reports) == 1
    r = reports[0]
    assert isinstance(r, PersistentMissReport)
    assert r.rung_label == "chatterbox"
    assert r.cold_count == 4
    assert r.threshold == 3
    assert r.offending_segment == "chatterbox"


# ------------------------------------------------------------------
# 7. streak interrupted by a warm turn
# ------------------------------------------------------------------


def test_persistent_miss_interrupted_by_warm():
    record_voice_turn(_make(is_cold=True, load_ms=500.0))
    record_voice_turn(_make(is_cold=True, load_ms=500.0))
    record_voice_turn(_make(is_cold=False))  # breaks the streak
    record_voice_turn(_make(is_cold=True, load_ms=500.0))
    reports = check_persistent_misses(threshold=3)
    assert reports == []


# ------------------------------------------------------------------
# 8. multiple rungs tracked independently
# ------------------------------------------------------------------


def test_persistent_miss_multiple_rungs():
    for _ in range(4):
        record_voice_turn(
            _make(is_cold=True, load_ms=500.0, rung_label="chatterbox"),
        )
    for _ in range(2):
        record_voice_turn(
            _make(is_cold=True, load_ms=300.0, rung_label="sherpa_onnx:kokoro-en"),
        )
    reports = check_persistent_misses(threshold=3)
    assert len(reports) == 1
    assert reports[0].rung_label == "chatterbox"


# ------------------------------------------------------------------
# 9. clear
# ------------------------------------------------------------------


def test_clear():
    record_voice_turn(_make())
    assert len(voice_turn_breakdowns()) == 1
    clear_voice_turn_breakdowns()
    assert voice_turn_breakdowns() == []


# ------------------------------------------------------------------
# 10. offending segment names the rung
# ------------------------------------------------------------------


def test_offending_segment():
    rung = "qwen3_tts:0.6b"
    for _ in range(5):
        record_voice_turn(_make(is_cold=True, load_ms=800.0, rung_label=rung))
    reports = check_persistent_misses(threshold=3)
    assert len(reports) == 1
    assert reports[0].offending_segment == rung
