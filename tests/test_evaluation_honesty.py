# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for evaluation honesty fixes (eval-honesty change).

Covers:
  H5 — embedder disclosure in A/B-divergence and memory-probe records,
       require_semantic_embedder fail-closed behaviour.
  H4 — eidolon_accuracy no longer advertises honest/open claims.
  M6 — curiosity is labelled a proxy in eidolon_accuracy output.
  L3 — empatheia observer skips pairings with absent confidence.
  L5 — Nous health probe performs a generative-model build check.
"""
from __future__ import annotations

import asyncio
import builtins
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.evaluation.ab_divergence import (
    ABDivergenceObserver,
    FakeBareInferenceClient,
)
from kaine.evaluation.config import EvaluationConfig
from kaine.evaluation.eidolon_accuracy import CLAIM_KEYWORDS, EidolonAccuracyRunner, parse_claims
from kaine.evaluation.embeddings import HashEmbedder, SentenceTransformerTextEmbedder
from kaine.evaluation.memory_probes import MemoryProbeRunner
from kaine.evaluation.observers.empatheia_observer import EmpatheiaObserver
from kaine.evaluation.registry import SidecarRegistry
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.nexus.health import DEGRADED, DOWN, UP, nous_health_probe


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _event(source: str, type_: str, payload: dict) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


class FakeBus:
    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, Event]]] = {}
        self._next = 1

    def push(self, stream: str, event: Event) -> str:
        eid = f"{self._next}-0"
        self._next += 1
        self.streams.setdefault(stream, []).append((eid, event))
        return eid

    async def read(self, stream, *, last_id="0", count=100, block_ms=0):
        entries = self.streams.get(stream, [])
        if last_id == "$":
            return []
        start = 0
        if last_id != "0":
            for i, (eid, _) in enumerate(entries):
                if eid == last_id:
                    start = i + 1
                    break
        return entries[start : start + count]

    async def read_entries(self, stream, last_id="0", count=100, block_ms=0):
        entries = await self.read(stream, last_id=last_id, count=count, block_ms=block_ms)
        last_scanned = entries[-1][0] if entries else None
        return entries, last_scanned

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        while True:
            await asyncio.sleep(poll_interval_s)
            if False:  # pragma: no cover
                yield

    async def current_workspace_id(self):
        return "0"


class _FakeMemorySource:
    def __init__(self, memory: dict | None = None) -> None:
        self._memory = memory

    async def sample_old_memory(self, *, older_than_seconds):
        return self._memory


class _FakeCognitiveClient:
    def __init__(self, response: str = "") -> None:
        self._response = response

    async def query(self, user_text: str) -> str:
        return self._response


# ---------------------------------------------------------------------------
# H5 — Embedder kind attribute
# ---------------------------------------------------------------------------


def test_hash_embedder_has_kind_hash():
    assert HashEmbedder().kind == "hash"


def test_sentence_transformer_embedder_has_kind_sentence_transformers():
    assert SentenceTransformerTextEmbedder.kind == "sentence_transformers"
    assert SentenceTransformerTextEmbedder().kind == "sentence_transformers"


# ---------------------------------------------------------------------------
# H5 — A/B-divergence record carries embedder field
# ---------------------------------------------------------------------------


class _CaptureSink:
    """In-memory sink that records written dicts."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    async def write(self, record: dict) -> None:
        self.records.append(record)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


@pytest.mark.asyncio
async def test_ab_divergence_record_carries_embedder_hash():
    bus = FakeBus()
    sink = _CaptureSink()
    embedder = HashEmbedder()
    client = FakeBareInferenceClient(response="bare answer")
    obs = ABDivergenceObserver(
        bus,
        sink,
        embedder=embedder,
        client=client,
        sample_rate=1.0,
        last_user_input_provider=lambda: "hello",
    )
    bus.push(
        "lingua.external",
        _event("lingua", "external_speech", {"text": "real answer", "user_input": "hello"}),
    )
    await obs.start()
    await asyncio.sleep(0.1)
    await obs.stop()
    assert sink.records, "no records written"
    assert sink.records[0]["embedder"] == "hash"


@pytest.mark.asyncio
async def test_ab_divergence_record_embedder_field_uses_kind_attribute():
    """Embedder kind is read from the .kind attribute, not hardcoded."""
    bus = FakeBus()
    sink = _CaptureSink()

    class CustomEmbedder:
        kind = "custom_test"

        async def load(self) -> None:
            pass

        async def embed(self, text: str) -> list[float]:
            return [0.5, 0.5]

    obs = ABDivergenceObserver(
        bus,
        sink,
        embedder=CustomEmbedder(),
        client=FakeBareInferenceClient(response="bare"),
        sample_rate=1.0,
        last_user_input_provider=lambda: "hello",
    )
    bus.push(
        "lingua.external",
        _event("lingua", "external_speech", {"text": "real", "user_input": "hello"}),
    )
    await obs.start()
    await asyncio.sleep(0.1)
    await obs.stop()
    assert sink.records[0]["embedder"] == "custom_test"


# ---------------------------------------------------------------------------
# H5 — Memory-probe record carries embedder field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_probe_record_carries_embedder_hash(tmp_path):
    sink = _CaptureSink()
    past_ts = "2000-01-01T00:00:00+00:00"
    memory = {"id": "m1", "timestamp": past_ts, "text": "old memory content"}
    obs = MemoryProbeRunner(
        sink,
        memory_source=_FakeMemorySource(memory),
        cognitive_client=_FakeCognitiveClient("I remember that"),
        bare_client=FakeBareInferenceClient(response="bare recall"),
        embedder=HashEmbedder(),
        interval_seconds=3600,
    )
    result = await obs.run_once()
    assert result is True
    assert sink.records, "no records written"
    assert sink.records[0]["embedder"] == "hash"


# ---------------------------------------------------------------------------
# H5 — require_semantic_embedder config flag
# ---------------------------------------------------------------------------


def test_require_semantic_embedder_default_is_false():
    cfg = EvaluationConfig.from_mapping({})
    assert cfg.require_semantic_embedder is False


def test_require_semantic_embedder_can_be_set_true():
    cfg = EvaluationConfig.from_mapping({"require_semantic_embedder": True})
    assert cfg.require_semantic_embedder is True


def test_require_semantic_embedder_raises_on_fallback(tmp_path):
    """When require_semantic_embedder=True and sentence_transformers is
    unavailable, _embedder_default must raise rather than silently
    returning HashEmbedder."""
    cfg = EvaluationConfig.from_mapping(
        {
            "require_semantic_embedder": True,
            "paths": {
                "trajectory_dir": str(tmp_path / "traj"),
                "evaluation_logs": str(tmp_path / "eval"),
            },
        }
    )
    registry = SidecarRegistry(bus=FakeBus(), config=cfg)

    class _AlwaysFail:
        def __init__(self, *a, **kw):
            raise RuntimeError("forced failure")

    # Patch the name in the registry module's namespace — that is what
    # _embedder_default() resolves when it constructs the semantic embedder.
    import kaine.evaluation.registry as reg_mod

    original_cls = reg_mod.SentenceTransformerTextEmbedder
    reg_mod.SentenceTransformerTextEmbedder = _AlwaysFail
    try:
        with pytest.raises(RuntimeError, match="require_semantic_embedder"):
            registry._embedder_default()
    finally:
        reg_mod.SentenceTransformerTextEmbedder = original_cls


def test_no_require_semantic_embedder_falls_back_silently(tmp_path, caplog):
    """When require_semantic_embedder=False (default), fallback logs at ERROR
    level but returns HashEmbedder without raising."""
    import logging

    cfg = EvaluationConfig.from_mapping(
        {
            "require_semantic_embedder": False,
            "paths": {
                "trajectory_dir": str(tmp_path / "traj"),
                "evaluation_logs": str(tmp_path / "eval"),
            },
        }
    )
    registry = SidecarRegistry(bus=FakeBus(), config=cfg)

    import kaine.evaluation.registry as reg_mod
    original_cls = reg_mod.SentenceTransformerTextEmbedder

    class _AlwaysFail:
        def __init__(self, *a, **kw):
            raise RuntimeError("forced failure")

    reg_mod.SentenceTransformerTextEmbedder = _AlwaysFail
    try:
        with caplog.at_level(logging.ERROR, logger="kaine.evaluation.registry"):
            result = registry._embedder_default()
        assert isinstance(result, HashEmbedder)
        assert any("LEXICAL" in r.message for r in caplog.records), (
            "expected ERROR log mentioning LEXICAL"
        )
    finally:
        reg_mod.SentenceTransformerTextEmbedder = original_cls


# ---------------------------------------------------------------------------
# H4 — eidolon_accuracy no longer advertises honest/open claims
# ---------------------------------------------------------------------------


def test_claim_keywords_does_not_contain_honest():
    assert "honest" not in CLAIM_KEYWORDS


def test_claim_keywords_does_not_contain_open():
    assert "open" not in CLAIM_KEYWORDS


def test_parse_claims_does_not_find_honest():
    # "honest" must not be extracted as a scoreable claim keyword.
    claims = parse_claims("I am honest and transparent")
    assert "honest" not in claims


def test_parse_claims_does_not_find_open():
    claims = parse_claims("I am open and curious")
    assert "open" not in claims


def test_claim_keywords_scores_supported_claims():
    # These should still be present (not accidentally removed).
    assert "curious" in CLAIM_KEYWORDS
    assert "cautious" in CLAIM_KEYWORDS
    assert "playful" in CLAIM_KEYWORDS
    assert "calm" in CLAIM_KEYWORDS
    assert "energetic" in CLAIM_KEYWORDS


# ---------------------------------------------------------------------------
# M6 — curiosity is labelled a proxy in eidolon output
# ---------------------------------------------------------------------------


def test_claim_keywords_curiosity_maps_to_proxy():
    assert CLAIM_KEYWORDS["curious"] == "curiosity_proxy"
    assert CLAIM_KEYWORDS["curiosity"] == "curiosity_proxy"


@pytest.mark.asyncio
async def test_eidolon_accuracy_curiosity_proxy_used_field(tmp_path):
    """When the entity self-describes as curious and the proactive_audit file
    exists, the output record must carry curiosity_proxy_used=True."""
    # Create a proactive_audit log with content.
    pa_dir = tmp_path / "eval" / "proactive_audit"
    pa_dir.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pa_file = pa_dir / f"proactive_audit-{today}.jsonl"
    pa_file.write_text('{"ts": "2026-06-09T00:00:00+00:00"}\n')

    sink = _CaptureSink()
    client = _FakeCognitiveClient("I am curious and engaged.")
    obs = EidolonAccuracyRunner(
        sink,
        cognitive_client=client,
        evaluation_logs_dir=tmp_path / "eval",
        interval_seconds=3600,
    )
    entry = await obs.run_once()
    assert "curiosity_proxy_used" in entry
    assert entry["curiosity_proxy_used"] is True


@pytest.mark.asyncio
async def test_eidolon_accuracy_curiosity_proxy_used_false_when_no_audit_file(tmp_path):
    """When no proactive_audit file exists, curiosity_proxy_used is False."""
    sink = _CaptureSink()
    client = _FakeCognitiveClient("I am curious.")
    obs = EidolonAccuracyRunner(
        sink,
        cognitive_client=client,
        evaluation_logs_dir=tmp_path / "eval",
        interval_seconds=3600,
    )
    entry = await obs.run_once()
    # No proactive_audit dir → curiosity_proxy_used must be False.
    assert entry["curiosity_proxy_used"] is False


# ---------------------------------------------------------------------------
# L3 — empatheia observer skips pairings with absent confidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empatheia_observer_skips_missing_confidence(tmp_path):
    """When audition.emotion event has no 'confidence' key, no record is written."""
    bus = FakeBus()
    sink = _CaptureSink()
    obs = EmpatheiaObserver(bus, sink, poll_interval_s=0.05)

    # Push a prediction.
    bus.push(
        "empatheia.out",
        _event("empatheia", "empatheia.agent_model", {
            "agent_id": "agent1",
            "reliability": 0.8,
            "familiarity": 0.5,
            "interaction_count": 3,
        }),
    )
    # Push an audition event WITHOUT confidence.
    bus.push(
        "audition.out",
        _event("audition", "audition.emotion", {
            "emotion": "neutral",
            # no 'confidence' key
        }),
    )
    await obs.start()
    await asyncio.sleep(0.15)
    await obs.stop()
    assert sink.records == [], (
        "empatheia observer must not write a record when confidence is absent"
    )


@pytest.mark.asyncio
async def test_empatheia_observer_scores_present_confidence(tmp_path):
    """When audition.emotion has 'confidence', the record is written with confidence_present=True."""
    bus = FakeBus()
    sink = _CaptureSink()
    obs = EmpatheiaObserver(bus, sink, poll_interval_s=0.05)

    bus.push(
        "empatheia.out",
        _event("empatheia", "empatheia.agent_model", {
            "agent_id": "agent1",
            "reliability": 0.8,
            "familiarity": 0.5,
            "interaction_count": 3,
        }),
    )
    bus.push(
        "audition.out",
        _event("audition", "audition.emotion", {
            "emotion": "happy",
            "confidence": 0.9,
        }),
    )
    await obs.start()
    await asyncio.sleep(0.15)
    await obs.stop()
    assert sink.records, "expected a record when confidence is present"
    rec = sink.records[0]
    assert rec["confidence_present"] is True
    assert rec["observed_confidence"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# L5 — Nous health probe performs a build check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nous_probe_up_includes_generative_model_built():
    """When pymdp+jax are importable, probe only returns UP if the
    generative model can be built."""
    pytest.importorskip("pymdp")
    pytest.importorskip("jax")
    status, detail = await nous_health_probe()
    assert status == UP
    assert "generative model built" in detail


@pytest.mark.asyncio
async def test_nous_probe_degraded_when_build_fails(monkeypatch):
    """When imports succeed but build_generative_model raises, probe returns DEGRADED."""
    pytest.importorskip("pymdp")
    pytest.importorskip("jax")

    import kaine.modules.nous.generative_model as gm_mod
    monkeypatch.setattr(
        gm_mod,
        "build_generative_model",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("build exploded")),
    )
    # Also patch the import inside health.py's _check closure.
    original = gm_mod.build_generative_model

    def _broken(**kw):
        raise RuntimeError("build exploded")

    monkeypatch.setattr(gm_mod, "build_generative_model", _broken)
    status, detail = await nous_health_probe()
    assert status == DEGRADED
    assert "build failed" in detail


@pytest.mark.asyncio
async def test_nous_probe_down_when_import_fails(monkeypatch):
    """Import failure still returns DOWN."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pymdp" or name.startswith("pymdp."):
            raise ImportError("pymdp not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    status, detail = await nous_health_probe()
    assert status == DOWN
    assert "import failed" in detail
