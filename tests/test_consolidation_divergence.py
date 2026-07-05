# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Consolidation divergence signal — the cheap, continuous organ-level
companion to the individuation permutation test.

Covers the spec scenarios for the `consolidation-divergence-signal` change:
counts/rate correctness; semantic magnitude (with a real-but-deterministic
embedder + the null-when-absent path); the metric emitted even when training is
skipped/rejected; the bus event/state record content-free; `assess_divergence`
flipping on threshold (independent of the individuation test + adapters) and NOT
from this signal alone below threshold; and the Nexus surface being numeric-only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.lifecycle.divergence import (
    DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD,
    DEFAULT_CONSOLIDATION_RATE_THRESHOLD,
    assess_divergence,
    consolidation_thresholds_from_config,
)
from kaine.modules.hypnos.module import Hypnos
from kaine.modules.hypnos.voice_alignment import (
    ConsolidationDivergence,
    DPOPair,
    DPOPairBuilder,
    FakeTrainer,
    VoiceAlignmentConfig,
    consolidation_magnitude,
    read_consolidation_divergence,
    write_consolidation_divergence,
)
from kaine.modules.hypnos.voice_alignment import OPERATOR_APPROVED_ENV
from kaine.text_embedding import HashEmbedder


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


# A mix of identical (no signal), divergent (usable), and degenerate records
# so the exact rate is computable: 5 scanned, 2 usable -> rate 0.4.
_MIXED = [
    {"prompt": "a", "faithful_rendering": "truth-1", "generated_text": "bare-1"},  # usable
    {"prompt": "b", "faithful_rendering": "same", "generated_text": "same"},       # identical
    {"prompt": "c", "faithful_rendering": "truth-3", "generated_text": "bare-3"},  # usable
    {"prompt": "d", "faithful_rendering": "", "generated_text": "bare-4"},         # no chosen
    {"prompt": "e", "faithful_rendering": "truth-5", "generated_text": "truth-5"}, # identical
]


class _FakeMnemos:
    async def consolidate_now(self) -> int:
        return 0

    def downscale_activations(self, factor: float) -> int:
        return 0

    async def replay_now(self) -> list:
        return []


class _FakeThymos:
    async def affective_reset(self) -> None:
        return None


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _make_hypnos(
    bus: AsyncBus,
    tmp_path: Path,
    *,
    intent_records: list[dict] | None,
    enabled: bool = True,
    trainer=None,
    embedder=None,
) -> Hypnos:
    log_path = tmp_path / "intent.jsonl"
    if intent_records is not None:
        _write_jsonl(log_path, intent_records)
    config = VoiceAlignmentConfig(
        intent_log_path=log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=enabled,
    )
    return Hypnos(
        bus,
        mnemos=_FakeMnemos(),
        thymos=_FakeThymos(),
        trainer=trainer or FakeTrainer(),
        voice_alignment_config=config,
        consolidation_embedder=embedder,
        consolidation_divergence_path=tmp_path / "consolidation_divergence.json",
    )


async def _read_consolidation_event(bus: AsyncBus) -> dict:
    entries = await bus.read("hypnos.out", last_id="0", count=50)
    evt = next(
        e for _, e in entries if e.type == "hypnos.consolidation_divergence"
    )
    return dict(evt.payload)


# --------------------------------------------------------------------------- #
# 1. Counts / rate correctness (builder)
# --------------------------------------------------------------------------- #


def test_build_with_counts_exact_rate(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    _write_jsonl(p, _MIXED)
    pairs, scanned, usable = DPOPairBuilder().build_with_counts(p, max_pairs=100)
    assert scanned == 5
    assert usable == 2
    assert len(pairs) == 2
    assert usable / max(1, scanned) == pytest.approx(0.4)


def test_usable_counts_full_numerator_past_max_pairs(tmp_path: Path):
    # 6 divergent records but a training budget of 2: the kept pairs cap at 2
    # while the usable-pair NUMERATOR counts all 6 for an honest rate.
    p = tmp_path / "log.jsonl"
    _write_jsonl(
        p,
        [
            {"prompt": str(i), "faithful_rendering": f"t{i}", "generated_text": f"g{i}"}
            for i in range(6)
        ],
    )
    pairs, scanned, usable = DPOPairBuilder().build_with_counts(p, max_pairs=2)
    assert len(pairs) == 2
    assert scanned == 6
    assert usable == 6


def test_build_missing_file_zero_counts(tmp_path: Path):
    pairs, scanned, usable = DPOPairBuilder().build_with_counts(
        tmp_path / "missing.jsonl", max_pairs=10
    )
    assert (pairs, scanned, usable) == ([], 0, 0)


# --------------------------------------------------------------------------- #
# 1.1 Semantic magnitude
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_magnitude_from_embeddings_is_mean_cosine_distance():
    # Deterministic embedder: identical-token pairs -> distance 0, disjoint-token
    # pairs -> distance 1. Mean over the two below is 0.5.
    pairs = [
        DPOPair(prompt="", chosen="alpha beta", rejected="alpha beta"),
        DPOPair(prompt="", chosen="alpha", rejected="omega"),
    ]
    magnitude, kind = await consolidation_magnitude(pairs, embedder=HashEmbedder())
    assert kind == "hash"
    assert magnitude == pytest.approx(0.5, abs=1e-9)


@pytest.mark.asyncio
async def test_magnitude_null_when_embedder_absent():
    pairs = [DPOPair(prompt="", chosen="a", rejected="b")]
    magnitude, kind = await consolidation_magnitude(pairs, embedder=None)
    assert magnitude is None
    assert kind is None


@pytest.mark.asyncio
async def test_magnitude_null_when_embedder_raises():
    class _Boom:
        kind = "boom"

        async def load(self) -> None:
            return None

        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("model unavailable")

    pairs = [DPOPair(prompt="", chosen="a", rejected="b")]
    magnitude, kind = await consolidation_magnitude(pairs, embedder=_Boom())
    assert magnitude is None
    assert kind is None


# --------------------------------------------------------------------------- #
# Emission via the sleep pipeline
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_emits_metric_with_correct_rate(bus: AsyncBus, tmp_path: Path, monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    hypnos = _make_hypnos(bus, tmp_path, intent_records=_MIXED, embedder=HashEmbedder())
    summary = await hypnos.enter_sleep()
    payload = await _read_consolidation_event(bus)
    assert payload["records_scanned"] == 5
    assert payload["usable_pairs"] == 2
    assert payload["divergence_rate"] == pytest.approx(0.4)
    assert payload["divergence_magnitude"] is not None
    assert payload["embedder"] == "hash"
    # Also threaded into the phase metadata.
    voice_phase = next(
        p for p in summary["phases"] if p["phase"] == "voice_alignment"
    )
    assert voice_phase["metadata"]["consolidation_divergence"]["usable_pairs"] == 2


@pytest.mark.asyncio
async def test_metric_emitted_even_when_training_disabled(
    bus: AsyncBus, tmp_path: Path, monkeypatch
):
    # config disabled => training skipped, but the divergence still happened.
    monkeypatch.delenv(OPERATOR_APPROVED_ENV, raising=False)
    hypnos = _make_hypnos(
        bus, tmp_path, intent_records=_MIXED, enabled=False, embedder=HashEmbedder()
    )
    summary = await hypnos.enter_sleep()
    payload = await _read_consolidation_event(bus)
    assert payload["usable_pairs"] == 2
    assert payload["divergence_rate"] == pytest.approx(0.4)
    voice_phase = next(
        p for p in summary["phases"] if p["phase"] == "voice_alignment"
    )
    assert voice_phase["metadata"]["training_skipped"] is True
    assert "consolidation_divergence" in voice_phase["metadata"]


@pytest.mark.asyncio
async def test_metric_emitted_when_not_operator_approved(
    bus: AsyncBus, tmp_path: Path, monkeypatch
):
    monkeypatch.delenv(OPERATOR_APPROVED_ENV, raising=False)
    hypnos = _make_hypnos(
        bus, tmp_path, intent_records=_MIXED, enabled=True, embedder=HashEmbedder()
    )
    await hypnos.enter_sleep()
    payload = await _read_consolidation_event(bus)
    assert payload["usable_pairs"] == 2


@pytest.mark.asyncio
async def test_metric_emitted_when_adapter_rejected(
    bus: AsyncBus, tmp_path: Path, monkeypatch
):
    # FakeTrainer rejects by default; the metric must still be emitted.
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    hypnos = _make_hypnos(
        bus, tmp_path, intent_records=_MIXED, embedder=HashEmbedder()
    )
    summary = await hypnos.enter_sleep()
    assert summary["voice_alignment"]["accepted"] is False
    payload = await _read_consolidation_event(bus)
    assert payload["usable_pairs"] == 2


@pytest.mark.asyncio
async def test_event_is_content_free(bus: AsyncBus, tmp_path: Path, monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    secret = "SECRET-UTTERANCE-TEXT"
    records = [
        {"prompt": secret, "faithful_rendering": secret + "-c", "generated_text": secret + "-r"},
    ]
    hypnos = _make_hypnos(bus, tmp_path, intent_records=records, embedder=HashEmbedder())
    await hypnos.enter_sleep()
    payload = await _read_consolidation_event(bus)
    blob = json.dumps(payload)
    assert secret not in blob
    assert set(payload) <= {
        "records_scanned",
        "usable_pairs",
        "divergence_rate",
        "divergence_magnitude",
        "embedder",
        "sleep_index",
    }
    for forbidden in ("prompt", "chosen", "rejected", "faithful_rendering", "generated_text", "text"):
        assert forbidden not in payload


# --------------------------------------------------------------------------- #
# State file round-trip (the seam assess_divergence reads)
# --------------------------------------------------------------------------- #


def test_state_file_roundtrip_content_free(tmp_path: Path):
    metric = ConsolidationDivergence(
        records_scanned=10,
        usable_pairs=7,
        divergence_rate=0.7,
        divergence_magnitude=0.31,
        embedder="hash",
    )
    path = tmp_path / "cons.json"
    write_consolidation_divergence(metric, sleep_index=3, path=path)
    data = read_consolidation_divergence(path)
    assert data["records_scanned"] == 10
    assert data["usable_pairs"] == 7
    assert data["divergence_rate"] == pytest.approx(0.7)
    assert data["divergence_magnitude"] == pytest.approx(0.31)
    assert data["sleep_index"] == 3
    assert "ts" in data


@pytest.mark.asyncio
async def test_sleep_writes_state_file(bus: AsyncBus, tmp_path: Path, monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    state = tmp_path / "consolidation_divergence.json"
    hypnos = _make_hypnos(bus, tmp_path, intent_records=_MIXED, embedder=HashEmbedder())
    await hypnos.enter_sleep()
    data = read_consolidation_divergence(state)
    assert data is not None
    assert data["usable_pairs"] == 2


# --------------------------------------------------------------------------- #
# 2. assess_divergence consumes the graded signal
# --------------------------------------------------------------------------- #


def _plant_consolidation(state_root: Path, *, rate: float, magnitude):
    d = state_root / "hypnos"
    d.mkdir(parents=True, exist_ok=True)
    metric = ConsolidationDivergence(
        records_scanned=100,
        usable_pairs=int(rate * 100),
        divergence_rate=rate,
        divergence_magnitude=magnitude,
        embedder="hash" if magnitude is not None else None,
    )
    write_consolidation_divergence(
        metric, sleep_index=1, path=d / "consolidation_divergence.json"
    )


def test_assess_flips_on_rate_threshold(tmp_path: Path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    # rate over threshold, magnitude null, no individuation report, no adapters.
    _plant_consolidation(state_root, rate=0.8, magnitude=None)
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged is True
    assert a.signals["consolidation_divergence_signal"] is True
    assert a.signals["consolidation_divergence_rate"] == pytest.approx(0.8)
    assert a.signals["hypnos_adapters_present"] is False
    assert a.signals["individuation_significant"] is False
    assert "consolidation divergence" in a.summary.lower()


def test_assess_flips_on_magnitude_threshold(tmp_path: Path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    # rate BELOW threshold but magnitude OVER threshold.
    _plant_consolidation(state_root, rate=0.1, magnitude=0.9)
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged is True
    assert a.signals["consolidation_divergence_signal"] is True
    assert a.signals["consolidation_divergence_magnitude"] == pytest.approx(0.9)


def test_assess_below_threshold_not_diverged(tmp_path: Path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    # Both below threshold; no other divergence condition.
    _plant_consolidation(state_root, rate=0.1, magnitude=0.05)
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged is False
    assert a.signals["consolidation_divergence_signal"] is False
    assert a.signals["consolidation_divergence_found"] is True
    assert "NOT DIVERGED" in a.summary


def test_assess_consolidation_independent_of_adapters_and_individuation(tmp_path: Path):
    # No adapters dir, no individuation report — consolidation alone drives it.
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    _plant_consolidation(state_root, rate=0.9, magnitude=None)
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged is True
    assert a.signals["individuation_report_found"] is False
    assert a.signals["hypnos_adapters_present"] is False


def test_assess_respects_config_thresholds(tmp_path: Path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    _plant_consolidation(state_root, rate=0.3, magnitude=None)
    # Default rate threshold 0.5 -> not diverged.
    a_default = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a_default.diverged is False
    # Lowered threshold 0.2 -> diverged.
    a_low = assess_divergence(
        state_root=state_root,
        eval_root=eval_root,
        consolidation_rate_threshold=0.2,
    )
    assert a_low.diverged is True


def test_consolidation_thresholds_from_config():
    assert consolidation_thresholds_from_config(None) == (
        DEFAULT_CONSOLIDATION_RATE_THRESHOLD,
        DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD,
    )
    cfg = {
        "hypnos": {
            "voice_alignment": {
                "consolidation_divergence_rate_threshold": 0.7,
                "consolidation_divergence_magnitude_threshold": 0.4,
            }
        }
    }
    assert consolidation_thresholds_from_config(cfg) == (0.7, 0.4)


def test_assess_never_raises_on_garbage_state(tmp_path: Path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    d = state_root / "hypnos"
    d.mkdir(parents=True, exist_ok=True)
    (d / "consolidation_divergence.json").write_text("{broken", encoding="utf-8")
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged in (True, False)


# --------------------------------------------------------------------------- #
# 3. Research event taxonomy + Nexus surface
# --------------------------------------------------------------------------- #


def test_research_taxonomy_has_consolidation_divergence():
    from kaine.evaluation.observers.research_event_observer import (
        _allowed_fields,
    )

    allowed = _allowed_fields("hypnos.consolidation_divergence")
    assert allowed is not None
    assert allowed == frozenset(
        {
            "records_scanned",
            "usable_pairs",
            "divergence_rate",
            "divergence_magnitude",
            "embedder",
            "sleep_index",
        }
    )


def test_research_record_is_numeric_only(tmp_path: Path):
    # A content-bearing payload is scrubbed to the numeric allowlist only.
    from kaine.bus.schema import Event
    from kaine.evaluation.observers.research_event_observer import (
        ResearchEventObserver,
    )
    from kaine.persistence.jsonl_sink import AsyncJsonlSink

    obs = ResearchEventObserver(
        bus=None, sink=AsyncJsonlSink(tmp_path / "re", name="research_events")
    )
    from datetime import datetime, timezone

    event = Event(
        type="hypnos.consolidation_divergence",
        source="hypnos",
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
        payload={
            "records_scanned": 5,
            "usable_pairs": 2,
            "divergence_rate": 0.4,
            "divergence_magnitude": 0.3,
            "embedder": "hash",
            "sleep_index": 1,
            # An accidental content leak must be dropped:
            "prompt": "leak",
            "text": "leak",
        },
    )
    record = obs._build_record(event)
    assert record is not None
    assert record["records_scanned"] == 5
    assert record["divergence_rate"] == 0.4
    assert "prompt" not in record
    assert "text" not in record


def test_nexus_entity_care_surfaces_numeric_consolidation(tmp_path: Path, monkeypatch):
    from kaine.nexus.health import HealthProber

    state_root = tmp_path / "state"
    _plant_consolidation(state_root, rate=0.8, magnitude=0.3)
    # assess_divergence defaults read state/... ; point cwd at tmp_path.
    monkeypatch.chdir(tmp_path)
    prober = HealthProber(modules_enabled={}, dependencies=[])
    block = prober._entity_care_block()
    sig = block["signals"]
    assert sig["consolidation_divergence_rate"] == pytest.approx(0.8)
    assert sig["consolidation_divergence_magnitude"] == pytest.approx(0.3)
    assert sig["consolidation_divergence_signal"] is True
    # Numeric/boolean only — no utterance text anywhere in the block.
    assert "SECRET" not in json.dumps(block)
