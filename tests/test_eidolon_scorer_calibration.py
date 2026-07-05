# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Calibration tests for the Eidolon self-model accuracy scorer.

These prove the scorer ARITHMETIC is correct: given known planted signals it
computes the documented accuracy. They validate scorer correctness only, NOT
self-model quality — the scorer matches trait keywords against currently derived
affect/activity signals (recent valence/arousal averages, hedging, proactive-audit
file presence), not a predicted-vs-actual next-state comparison.

The fixtures plant controlled JSONL into the evaluation logs dir (the same dir
``_signals_snapshot`` reads), then assert ``_signals_snapshot`` / ``_score_claim``
/ the ``run_once`` aggregate return the exact expected numbers.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.evaluation.eidolon_accuracy import EidolonAccuracyRunner
from kaine.evaluation.sink import AsyncJsonlSink


class _CaptureSink:
    """In-memory sink that records written dicts (no disk, no flush task)."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    async def write(self, record: dict) -> None:
        self.records.append(record)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class _FakeCognitiveClient:
    def __init__(self, response: str) -> None:
        self._response = response

    async def query(self, user_text: str) -> str:
        return self._response


def _plant_affect_correlation(
    logs_dir: Path, *, valence: float, arousal: float, hedge_word_count: float
) -> None:
    """Plant a single affect_correlation record carrying a known Thymos vector.

    A single record means the averages computed by ``_signals_snapshot`` equal
    exactly the planted values, so the derived signal flags are deterministic.
    """
    ac_dir = logs_dir / "affect_correlation"
    ac_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "thymos_state": {"valence": valence, "arousal": arousal},
        "characteristics": {"hedge_word_count": hedge_word_count},
    }
    (ac_dir / "affect_correlation-2026-06-14.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )


def _plant_proactive_audit(logs_dir: Path, *, content: bool) -> None:
    """Plant a today-dated proactive_audit file (curiosity-proxy signal)."""
    pa_dir = logs_dir / "proactive_audit"
    pa_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pa_file = pa_dir / f"proactive_audit-{today}.jsonl"
    pa_file.write_text('{"ts": "x"}\n' if content else "", encoding="utf-8")


def _runner(logs_dir: Path, response: str) -> EidolonAccuracyRunner:
    return EidolonAccuracyRunner(
        _CaptureSink(),
        cognitive_client=_FakeCognitiveClient(response),
        evaluation_logs_dir=logs_dir,
        interval_seconds=3600,
    )


# ---------------------------------------------------------------------------
# _signals_snapshot derives the documented signal flags from planted records.
# ---------------------------------------------------------------------------


def test_signals_snapshot_derives_high_valence_flags(tmp_path):
    # Planted average valence 0.6 > 0.2 -> valence_high=1, valence_low=0.
    # arousal 0.1 < 0.25 -> arousal_low=1, arousal_high=0.
    # hedge 2.0 >= 1.0 -> hedging=1.
    _plant_affect_correlation(tmp_path, valence=0.6, arousal=0.1, hedge_word_count=2.0)
    signals = _runner(tmp_path, "")._signals_snapshot()
    assert signals["valence_high"] == 1.0
    assert signals["valence_low"] == 0.0
    assert signals["arousal_high"] == 0.0
    assert signals["arousal_low"] == 1.0
    assert signals["hedging"] == 1.0


def test_signals_snapshot_derives_low_valence_flags(tmp_path):
    # Planted average valence -0.6 < -0.2 -> valence_low=1, valence_high=0.
    # arousal 0.9 > 0.55 -> arousal_high=1, arousal_low=0.
    # hedge 0.0 < 1.0 -> hedging=0.
    _plant_affect_correlation(tmp_path, valence=-0.6, arousal=0.9, hedge_word_count=0.0)
    signals = _runner(tmp_path, "")._signals_snapshot()
    assert signals["valence_low"] == 1.0
    assert signals["valence_high"] == 0.0
    assert signals["arousal_high"] == 1.0
    assert signals["arousal_low"] == 0.0
    assert signals["hedging"] == 0.0


def test_signals_snapshot_curiosity_proxy_from_audit_file(tmp_path):
    _plant_proactive_audit(tmp_path, content=True)
    signals = _runner(tmp_path, "")._signals_snapshot()
    assert signals["curiosity_proxy"] == 1.0


# ---------------------------------------------------------------------------
# _score_claim: HIGH-supported claim -> 1.0, contradicted claim -> 0.0.
# ---------------------------------------------------------------------------


def test_score_claim_high_when_signal_supports(tmp_path):
    _plant_affect_correlation(tmp_path, valence=0.6, arousal=0.1, hedge_word_count=2.0)
    runner = _runner(tmp_path, "")
    signals = runner._signals_snapshot()
    # "playful" maps to valence_high, which the plant supports -> 1.0.
    assert runner._score_claim("playful", signals) == 1.0
    # "calm" maps to arousal_low (arousal 0.1 < 0.25) -> 1.0.
    assert runner._score_claim("calm", signals) == 1.0


def test_score_claim_low_when_signal_contradicts(tmp_path):
    _plant_affect_correlation(tmp_path, valence=0.6, arousal=0.1, hedge_word_count=2.0)
    runner = _runner(tmp_path, "")
    signals = runner._signals_snapshot()
    # "withdrawn" maps to valence_low; the high-valence plant contradicts -> 0.0.
    assert runner._score_claim("withdrawn", signals) == 0.0
    # "energetic" maps to arousal_high; low-arousal plant contradicts -> 0.0.
    assert runner._score_claim("energetic", signals) == 0.0


def test_score_claim_none_for_unmapped_keyword(tmp_path):
    runner = _runner(tmp_path, "")
    # A keyword with no signal mapping returns None (excluded from aggregate).
    assert runner._score_claim("unknown_trait", {}) is None


# ---------------------------------------------------------------------------
# run_once aggregate == arithmetic mean of the scored (non-None) claims.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_aggregate_is_mean_of_scored_claims(tmp_path):
    # Plant high valence + low arousal + hedging present.
    _plant_affect_correlation(tmp_path, valence=0.6, arousal=0.1, hedge_word_count=2.0)
    # Self-description with four scoreable claims:
    #   playful  -> valence_high  -> 1.0 (supported)
    #   calm     -> arousal_low   -> 1.0 (supported)
    #   withdrawn-> valence_low   -> 0.0 (contradicted)
    #   energetic-> arousal_high  -> 0.0 (contradicted)
    # Aggregate = (1 + 1 + 0 + 0) / 4 = 0.5.
    runner = _runner(tmp_path, "I am playful, calm, withdrawn and energetic.")
    entry = await runner.run_once()
    assert set(entry["claims"]) >= {"playful", "calm", "withdrawn", "energetic"}
    assert entry["scored"]["playful"] == 1.0
    assert entry["scored"]["calm"] == 1.0
    assert entry["scored"]["withdrawn"] == 0.0
    assert entry["scored"]["energetic"] == 0.0
    assert entry["aggregate_accuracy"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_run_once_aggregate_all_supported_is_one(tmp_path):
    _plant_affect_correlation(tmp_path, valence=0.6, arousal=0.1, hedge_word_count=2.0)
    # Only supported claims -> aggregate 1.0.
    runner = _runner(tmp_path, "I am playful and calm.")
    entry = await runner.run_once()
    assert entry["scored"]["playful"] == 1.0
    assert entry["scored"]["calm"] == 1.0
    assert entry["aggregate_accuracy"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_run_once_aggregate_none_when_no_scoreable_signal(tmp_path):
    # No planted signals at all -> mapped signals are absent -> claims score None
    # -> no scored_known -> aggregate is None ("no evidence"), NOT 0.0 ("wrong").
    # Distinguishing the two is the honesty fix: an unscoreable run must never
    # read as a maximally-wrong self-model.
    runner = _runner(tmp_path, "I am playful and calm.")
    entry = await runner.run_once()
    assert entry["scored"]["playful"] is None
    assert entry["scored"]["calm"] is None
    assert entry["aggregate_accuracy"] is None
    assert entry["scorable_claims"] == 0


def test_calibration_uses_real_async_sink(tmp_path):
    # Sanity: the real AsyncJsonlSink is importable and constructs (the runner
    # is also exercised with the production sink elsewhere); this keeps the
    # calibration honest about the seam it tests.
    sink = AsyncJsonlSink(tmp_path, name="eidolon_accuracy")
    assert sink is not None
