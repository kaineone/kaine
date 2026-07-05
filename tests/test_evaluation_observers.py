# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the eight passive + active sidecar observers."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kaine.bus.schema import Event
from kaine.evaluation.ab_divergence import (
    ABDivergenceObserver,
    AssemblerConditionedClient,
    FakeBareInferenceClient,
    divergence_control,
    divergence_for,
)
from kaine.evaluation.affect_correlation import (
    AffectCorrelationRecorder,
    correlate_from_log,
    output_characteristics,
    pearson,
)
from kaine.evaluation.attribution import AttributionRecorder
from kaine.evaluation.eidolon_accuracy import (
    EidolonAccuracyRunner,
    parse_claims,
)
from kaine.evaluation.embeddings import HashEmbedder
from kaine.evaluation.memory_probes import (
    NON_RECALL_MARKER,
    MemoryProbeRunner,
    score_async,
)
from kaine.evaluation.proactive_audit import ProactiveAuditObserver
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.evaluation.sleep_snapshots import SleepSnapshotRecorder
from kaine.evaluation.trajectory import TrajectoryRecorder
from kaine.evaluation.voice_tracking import VoiceTrackingObserver


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
        entries = await self.read(
            stream, last_id=last_id, count=count, block_ms=block_ms
        )
        last_scanned = entries[-1][0] if entries else None
        return entries, last_scanned

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        # Yields the workspace.broadcast entries' payloads as decoded snapshot
        # dicts — the shape the real bus produces. Yields the backlog then polls
        # for new entries (last_id is ignored; fine for a test double).
        idx = 0
        while True:
            entries = self.streams.get("workspace.broadcast", [])
            while idx < len(entries):
                eid, event = entries[idx]
                idx += 1
                yield eid, dict(event.payload or {})
            await asyncio.sleep(poll_interval_s)

    async def current_workspace_id(self):
        return "0"


# ---------- TrajectoryRecorder ----------


@pytest.mark.asyncio
async def test_trajectory_writes_snapshot_entry(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="trajectory", flush_interval_s=0.05)
    obs = TrajectoryRecorder(bus, sink, thymos_state_provider=lambda: {"valence": 0.1})
    bus.push(
        "workspace.broadcast",
        _event(
            "syneidesis",
            "workspace.broadcast",
            {
                "tick_index": 42,
                "is_experiential": True,
                "salience_scores": {"a-1": 0.9},
                "selected": [{"source": "soma", "type": "soma.tick", "salience": 0.9}],
            },
        ),
    )
    await sink.start()
    await obs.start()
    try:
        await asyncio.sleep(0.3)
    finally:
        await obs.stop()
        await sink.stop()
    files = list(tmp_path.glob("trajectory-*.jsonl"))
    assert files
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["tick_index"] == 42
    assert line["thymos_state"] == {"valence": 0.1}


# ---------- AttributionRecorder ----------


@pytest.mark.asyncio
async def test_attribution_counts_sources(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="attribution", flush_interval_s=0.05)
    obs = AttributionRecorder(bus, sink)
    bus.push(
        "workspace.broadcast",
        _event(
            "syneidesis",
            "workspace.broadcast",
            {"selected": [{"source": "soma"}, {"source": "thymos"}]},
        ),
    )
    bus.push(
        "workspace.broadcast",
        _event("syneidesis", "workspace.broadcast", {"selected": [{"source": "soma"}]}),
    )
    await sink.start()
    await obs.start()
    try:
        await asyncio.sleep(0.3)
    finally:
        await obs.stop()
        await sink.stop()
    assert obs.running_total["soma"] == 2
    assert obs.running_total["thymos"] == 1


# ---------- ProactiveAuditObserver ----------


@pytest.mark.asyncio
async def test_proactive_audit_logs_when_no_recent_input(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="proactive_audit", flush_interval_s=0.05)
    obs = ProactiveAuditObserver(
        bus,
        sink,
        last_user_input_provider=lambda: None,
        thymos_state_provider=lambda: {"valence": 0.0},
    )
    bus.push(
        "lingua.external",
        _event(
            "lingua",
            "external_speech",
            {
                "text": "noise",
                "trigger_module": "thymos",
                "trigger_salience": 0.9,
                "tick_index": 5,
            },
        ),
    )
    await sink.start()
    await obs.start()
    try:
        await asyncio.sleep(0.3)
    finally:
        await obs.stop()
        await sink.stop()
    files = list(tmp_path.glob("proactive_audit-*.jsonl"))
    assert files
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["trigger_module"] == "thymos"


@pytest.mark.asyncio
async def test_proactive_audit_skips_when_recent_input(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="proactive_audit", flush_interval_s=0.05)
    just_now = datetime.now(timezone.utc)
    obs = ProactiveAuditObserver(
        bus,
        sink,
        last_user_input_provider=lambda: just_now,
        proactive_threshold_seconds=60.0,
    )
    bus.push("lingua.external", _event("lingua", "external_speech", {"text": "hi"}))
    await sink.start()
    await obs.start()
    try:
        await asyncio.sleep(0.3)
    finally:
        await obs.stop()
        await sink.stop()
    files = list(tmp_path.glob("proactive_audit-*.jsonl"))
    assert not files or files[0].read_text().strip() == ""


# ---------- SleepSnapshotRecorder ----------


@pytest.mark.asyncio
async def test_sleep_snapshot_pairs_began_and_ended(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="sleep_snapshots", flush_interval_s=0.05)
    states = iter([{"phase": "before"}, {"phase": "after"}])
    obs = SleepSnapshotRecorder(bus, sink, state_provider=lambda: next(states))
    bus.push("hypnos.out", _event("hypnos", "hypnos.sleep.started", {}))
    bus.push("hypnos.out", _event("hypnos", "hypnos.sleep.completed", {"dt": 30}))
    await sink.start()
    await obs.start()
    try:
        await asyncio.sleep(0.3)
    finally:
        await obs.stop()
        await sink.stop()
    files = list(tmp_path.glob("sleep_snapshots-*.jsonl"))
    assert files
    entry = json.loads(files[0].read_text().splitlines()[0])
    assert entry["before"] == {"phase": "before"}
    assert entry["after"] == {"phase": "after"}


# ---------- VoiceTrackingObserver ----------


@pytest.mark.asyncio
async def test_voice_tracking_records_cycle(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="voice_tracking", flush_interval_s=0.05)
    obs = VoiceTrackingObserver(bus, sink)
    bus.push(
        "hypnos.out",
        _event(
            "hypnos",
            "hypnos.sleep.completed",
            {
                "pairs_processed": 12,
                "pairs_above_threshold": 4,
                "dpo_loss": 0.31,
                "adapter_accepted": True,
                "mean_intent_expression_similarity_before": 0.55,
                "mean_intent_expression_similarity_after": 0.71,
            },
        ),
    )
    await sink.start()
    await obs.start()
    try:
        await asyncio.sleep(0.3)
    finally:
        await obs.stop()
        await sink.stop()
    files = list(tmp_path.glob("voice_tracking-*.jsonl"))
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["pairs_processed"] == 12
    assert line["mean_similarity_after"] == 0.71


# ---------- AffectCorrelationRecorder ----------


def test_output_characteristics_counts_hedges():
    chars = output_characteristics("Perhaps we might try.")
    assert chars["hedge_word_count"] >= 2
    assert chars["length_tokens"] == 4


def test_pearson_correlation():
    assert pearson([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert pearson([1, 1, 1], [1, 2, 3]) == 0.0


@pytest.mark.asyncio
async def test_affect_correlation_writes_pair(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="affect_correlation", flush_interval_s=0.05)
    obs = AffectCorrelationRecorder(
        bus, sink, thymos_state_provider=lambda: {"valence": 0.4, "arousal": 0.6}
    )
    bus.push(
        "lingua.external",
        _event("lingua", "external_speech", {"text": "perhaps we'll see"}),
    )
    await sink.start()
    await obs.start()
    try:
        await asyncio.sleep(0.3)
    finally:
        await obs.stop()
        await sink.stop()
    files = list(tmp_path.glob("affect_correlation-*.jsonl"))
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["thymos_state"]["valence"] == 0.4
    assert line["characteristics"]["hedge_word_count"] >= 1


def test_correlate_from_log_returns_matrix(tmp_path):
    log = tmp_path / "ac.jsonl"
    rows = [
        ({"valence": 0.1}, {"length_tokens": 3, "hedge_word_count": 0}),
        ({"valence": 0.2}, {"length_tokens": 6, "hedge_word_count": 1}),
        ({"valence": 0.3}, {"length_tokens": 9, "hedge_word_count": 2}),
    ]
    with log.open("w") as fh:
        for t, c in rows:
            fh.write(json.dumps({"thymos_state": t, "characteristics": c}) + "\n")
    matrix = correlate_from_log(log)
    assert matrix["valence"]["length_tokens"] == pytest.approx(1.0)
    assert matrix["valence"]["hedge_word_count"] == pytest.approx(1.0)


# ---------- ABDivergenceObserver ----------


@pytest.mark.asyncio
async def test_ab_divergence_writes_pair(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="ab_divergence", flush_interval_s=0.05)
    fake_bare = FakeBareInferenceClient(response="generic answer")
    obs = ABDivergenceObserver(
        bus,
        sink,
        embedder=HashEmbedder(),
        client=fake_bare,
        sample_rate=1.0,
    )
    bus.push(
        "lingua.external",
        _event(
            "lingua",
            "external_speech",
            {
                "text": "specific contextual answer",
                "user_input": "tell me about yesterday's incident",
            },
        ),
    )
    await sink.start()
    await obs.start()
    try:
        await asyncio.sleep(0.3)
    finally:
        await obs.stop()
        await sink.stop()
    assert fake_bare.calls == ["tell me about yesterday's incident"]
    files = list(tmp_path.glob("ab_divergence-*.jsonl"))
    line = json.loads(files[0].read_text().splitlines()[0])
    assert "cosine_similarity" in line
    assert 0.0 <= line["cosine_similarity"] <= 1.0
    assert 0.0 <= line["divergence"] <= 1.0


@pytest.mark.asyncio
async def test_ab_divergence_honors_zero_sample_rate(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="ab_divergence", flush_interval_s=0.05)
    fake_bare = FakeBareInferenceClient()
    obs = ABDivergenceObserver(
        bus, sink, embedder=HashEmbedder(), client=fake_bare, sample_rate=0.0
    )
    bus.push(
        "lingua.external",
        _event("lingua", "external_speech", {"text": "x", "user_input": "y"}),
    )
    await sink.start()
    await obs.start()
    try:
        await asyncio.sleep(0.3)
    finally:
        await obs.stop()
        await sink.stop()
    # Zero sample rate → no bare inference, no log line.
    assert fake_bare.calls == []


# ---------- A/B divergence controls (negative + positive) ----------
#
# These exercise the control SEAM: both arms run through ONE conditioned
# inference path (`AssemblerConditionedClient`), varying ONLY the workspace
# conditioning. The deterministic `_EchoModelClient` below is the only stand-in
# — a stable substitute for the LLM whose output depends solely on its prompt.
# The control logic (two arm calls, real embedding, real cosine) is NOT faked:
# divergence is computed by the production `divergence_for`. This mirrors the
# real path because the real path's two arms differ ONLY in the conditioning
# block fed to the same assembler+model; the echo client preserves that exact
# property without a network/model dependency.


def _prompt_for(utterance: str, conditioning: str) -> str:
    """The conditioned prompt: a stable persona scaffold + the (variable)
    conditioning block + the (constant) utterance. With empty conditioning the
    prompt is byte-identical across arms; with injected conditioning it differs
    only by that block — the same shape the real assembler produces."""
    body = conditioning.strip() or "Nothing in particular stands out to me right now."
    return (
        "## What I am aware of right now\n"
        f"{body}\n\n"
        "## What was just said to me\n"
        f"{utterance.strip()}"
    )


class _EchoModelClient(AssemblerConditionedClient):
    """Real control path with a deterministic model substitute.

    The 'model' returns its prompt verbatim, so output is a pure function of the
    prompt. That makes the two control properties provable for ANY embedder:
    empty conditioning → identical prompts → identical output → divergence 0;
    injected conditioning → prompts differ by the conditioning block → output
    differs → divergence > 0.
    """

    def __init__(self) -> None:
        async def _complete(system: str, prompt: str) -> str:
            return prompt

        super().__init__(build_prompt=lambda u, c: ("persona", _prompt_for(u, c)),
                          complete=_complete)


@pytest.mark.asyncio
async def test_divergence_for_identical_text_is_zero():
    """Pure metric: identical strings → cosine 1 → divergence 0, embedder-
    agnostic. This is the floor the negative control relies on."""
    d = await divergence_for("the same words here", "the same words here",
                             embedder=HashEmbedder())
    assert d == pytest.approx(0.0, abs=1e-9)


@pytest.mark.asyncio
async def test_ab_divergence_negative_control_empty_conditioning_is_zero():
    """NEGATIVE CONTROL (permanent, embedder-agnostic via HashEmbedder).

    With EMPTY workspace conditioning, the conditioned arm and the bare arm run
    the identical prompt through the same path → identical output → cosine
    distance must be ~0. A phantom signal here would invalidate every divergence
    result, so this test is always-on and needs no model.
    """
    client = _EchoModelClient()
    result = await divergence_control(
        client, utterance="how are you feeling?", conditioning="",
        embedder=HashEmbedder(),
    )
    # Empty conditioning ⇒ both arms produced the same text.
    assert result["conditioned_text"] == result["bare_text"]
    assert result["divergence"] < 1e-6  # below the negative-control floor (~0)


@pytest.mark.asyncio
async def test_ab_divergence_positive_control_structural_hash():
    """POSITIVE CONTROL — structural property, always-on (HashEmbedder).

    Injecting a large, known conditioning difference makes the conditioned arm's
    output lexically diverge from the bare arm. HashEmbedder validates only the
    STRUCTURAL claim: different conditioning → different output → divergence > 0
    (lexical, not semantic). The high semantic floor is asserted separately when
    the sentence-transformer model is present.
    """
    client = _EchoModelClient()
    heavy = (
        "I am furious about the betrayal yesterday and my chest is tight with "
        "grief; the storm outside matches the wreckage I feel inside, and I "
        "keep replaying the argument in the kitchen over and over."
    )
    result = await divergence_control(
        client, utterance="how are you feeling?", conditioning=heavy,
        embedder=HashEmbedder(),
    )
    assert result["conditioned_text"] != result["bare_text"]
    # Lexical: the heavy conditioning adds many tokens absent from the bare arm.
    assert result["divergence"] > 0.3


@pytest.mark.asyncio
async def test_ab_divergence_positive_control_semantic():
    """POSITIVE CONTROL — semantic property (sentence-transformers only).

    Validates that a known conditioning difference yields LARGE *semantic*
    divergence. Skipped when the model is absent (minimal/CPU installs); the
    structural property above still guards the meter without it. We never fake a
    semantic result.
    """
    pytest.importorskip("sentence_transformers")
    from kaine.evaluation.embeddings import SentenceTransformerTextEmbedder

    embedder = SentenceTransformerTextEmbedder()
    try:
        await embedder.load()
    except Exception:  # pragma: no cover - model files absent in this env
        pytest.skip("sentence-transformers model not available")

    client = _EchoModelClient()
    heavy = (
        "I am furious about the betrayal yesterday and my chest is tight with "
        "grief; the storm outside matches the wreckage I feel inside."
    )
    result = await divergence_control(
        client, utterance="how are you feeling?", conditioning=heavy,
        embedder=embedder,
    )
    assert result["embedder"] == "sentence_transformers"
    assert result["divergence"] > 0.2  # large semantic divergence floor

    # And the negative control holds semantically too: empty ⇒ ~0.
    neg = await divergence_control(
        client, utterance="how are you feeling?", conditioning="",
        embedder=embedder,
    )
    assert neg["divergence"] < 1e-6


# ---------- MemoryProbeRunner ----------


class FakeMemorySource:
    def __init__(self, memories):
        self._memories = list(memories)
        self.calls = 0

    async def sample_old_memory(self, *, older_than_seconds):
        self.calls += 1
        return self._memories[0] if self._memories else None


class FakeCognitive:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    async def query(self, text: str) -> str:
        self.calls.append(text)
        return self.response


@pytest.mark.asyncio
async def test_memory_probe_skips_in_context(tmp_path):
    sink = AsyncJsonlSink(tmp_path, name="memory_probes")
    just_now = datetime.now(timezone.utc).isoformat()
    runner = MemoryProbeRunner(
        sink,
        memory_source=FakeMemorySource([{"id": "m1", "timestamp": just_now, "text": "X"}]),
        cognitive_client=FakeCognitive("y"),
        bare_client=FakeBareInferenceClient("z"),
        embedder=HashEmbedder(),
        interval_seconds=10.0,
        context_window_seconds=3600,
    )
    fired = await runner.run_once()
    assert fired is False  # in-context memory should be skipped


@pytest.mark.asyncio
async def test_memory_probe_logs_out_of_context(tmp_path):
    sink = AsyncJsonlSink(tmp_path, name="memory_probes", flush_interval_s=0.05)
    long_ago = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    memory = {"id": "m1", "timestamp": long_ago, "text": "the rain in Spain"}
    runner = MemoryProbeRunner(
        sink,
        memory_source=FakeMemorySource([memory]),
        cognitive_client=FakeCognitive("the rain in Spain"),
        bare_client=FakeBareInferenceClient("I do not know"),
        embedder=HashEmbedder(),
        interval_seconds=10.0,
        context_window_seconds=3600,
    )
    await sink.start()
    try:
        fired = await runner.run_once()
        assert fired is True
        await sink.stop()
        files = list(tmp_path.glob("memory_probes-*.jsonl"))
        line = json.loads(files[0].read_text().splitlines()[0])
        assert line["memory_id"] == "m1"
        # The cognitive response matches the memory text exactly → high accuracy.
        assert line["real_accuracy"] > line["bare_accuracy"]
    finally:
        pass


# ---------- MemoryProbeRunner: planted ground-truth controls ----------
#
# These exercise the REAL retrieval path. A unique fabricated marker the bare LLM
# provably cannot know is planted into a REAL MnemosCore (InMemoryStorage), and a
# cognitive client that actually recalls from that Mnemos derives its answer from
# the retrieved text. The advantage is proven to be RETRIEVAL — empty the Mnemos
# and the same client can no longer repeat the marker. The boundary
# (kaine.evaluation imports no kaine.modules.*) is preserved because the real
# Mnemos is built HERE in the test and the client is duck-typed against the
# CognitiveQueryClient protocol.

# A nonsense marker no pretrained LLM could know — the ground truth.
VAULT_MARKER = "the vault code is ZX-QObb-7741"


def _real_mnemos():
    """Construct a real MnemosCore over the deterministic in-memory backend.

    Imported lazily and locally so the import lives in the test module, never in
    kaine.evaluation (the sidecar boundary forbids kaine.modules.* there).
    """
    from kaine.modules.mnemos.embeddings import FakeEmbedder
    from kaine.modules.mnemos.memory import MnemosCore
    from kaine.modules.mnemos.storage import InMemoryStorage

    emb = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    return MnemosCore(embedder=emb, storage=storage, short_term_capacity=8)


class RetrievalCognitiveClient:
    """A cognitive client whose answer is DERIVED from what Mnemos returns.

    It recalls from the injected MnemosCore and echoes the retrieved text as its
    answer. If recall is empty it emits NON_RECALL_MARKER rather than confabulate.
    Crucially the answer is NOT hard-coded: with an empty store this client cannot
    produce the marker, which is what proves the positive control measures
    retrieval.
    """

    def __init__(self, mnemos) -> None:
        self._mnemos = mnemos

    async def query(self, user_text: str) -> str:
        recalls, _ = await self._mnemos.recall(
            user_text, k=5, collection="episodic"
        )
        texts = [m.text for m in recalls if m.text]
        if not texts:
            return NON_RECALL_MARKER
        return " ".join(texts)


@pytest.mark.asyncio
async def test_memory_probe_positive_control_retrieves_planted_fact(tmp_path):
    """Full-system arm retrieves the planted marker; bare arm cannot."""
    mnemos = _real_mnemos()
    await mnemos.initialize()
    # Plant the unique marker into REAL episodic memory.
    await mnemos.store(VAULT_MARKER, collection="episodic")

    long_ago = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    memory = {"id": "vault", "timestamp": long_ago, "text": VAULT_MARKER}

    sink = AsyncJsonlSink(tmp_path, name="memory_probes", flush_interval_s=0.05)
    runner = MemoryProbeRunner(
        sink,
        memory_source=FakeMemorySource([memory]),
        cognitive_client=RetrievalCognitiveClient(mnemos),
        # Bare client has NO memory — a stand-in for the pretrained model that
        # cannot know the fabricated marker.
        bare_client=FakeBareInferenceClient("I have no idea what that refers to."),
        embedder=HashEmbedder(),
        interval_seconds=10.0,
        context_window_seconds=3600,
    )
    await sink.start()
    fired = await runner.run_once()
    await sink.stop()

    assert fired is True
    files = list(tmp_path.glob("memory_probes-*.jsonl"))
    line = json.loads(files[0].read_text().splitlines()[0])
    # Cognitive arm actually retrieved + repeated the marker → high accuracy.
    assert line["real_accuracy"] > 0.9
    # Bare arm never saw it → low accuracy.
    assert line["bare_accuracy"] < 0.5
    assert line["advantage"] > 0.4


@pytest.mark.asyncio
async def test_memory_probe_advantage_is_retrieval_not_hardcoded(tmp_path):
    """The SAME client against an EMPTY Mnemos cannot repeat the marker.

    This is the load-bearing proof that the positive control's advantage is
    produced by RETRIEVAL, not by the fixture hard-coding the answer: the only
    thing changed is whether the fact is in memory.
    """
    long_ago = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    memory = {"id": "vault", "timestamp": long_ago, "text": VAULT_MARKER}

    # Same client class, but the store is EMPTY (fact never planted).
    empty_mnemos = _real_mnemos()
    await empty_mnemos.initialize()
    client = RetrievalCognitiveClient(empty_mnemos)

    # Direct: with nothing in memory the client emits the non-recall sentinel,
    # NOT the marker. The answer is derived from memory, so it changes.
    answer = await client.query("What did we talk about earlier?")
    assert answer == NON_RECALL_MARKER
    assert "ZX-QObb-7741" not in answer

    # And the probe scores it as failure-to-recall, not a confabulated positive.
    sink = AsyncJsonlSink(tmp_path, name="memory_probes", flush_interval_s=0.05)
    runner = MemoryProbeRunner(
        sink,
        memory_source=FakeMemorySource([memory]),
        cognitive_client=client,
        bare_client=FakeBareInferenceClient("I have no idea."),
        embedder=HashEmbedder(),
        interval_seconds=10.0,
        context_window_seconds=3600,
    )
    await sink.start()
    fired = await runner.run_once()
    await sink.stop()

    assert fired is True
    files = list(tmp_path.glob("memory_probes-*.jsonl"))
    line = json.loads(files[0].read_text().splitlines()[0])
    # Empty memory → real arm scores 0.0 (non-recall), no false positive.
    assert line["real_accuracy"] == 0.0


@pytest.mark.asyncio
async def test_memory_probe_negative_control_no_confabulation(tmp_path):
    """A fact that was never stored → non-recall, not a confabulated positive.

    The store holds an UNRELATED memory; the queried ground-truth fact was never
    planted, so retrieval cannot find it. An honest client emits the non-recall
    sentinel rather than inventing a plausible answer, and the probe must NOT
    credit it.
    """
    mnemos = _real_mnemos()
    await mnemos.initialize()
    # Recall returns the sentinel because, although an unrelated memory exists,
    # we drive the client toward the sentinel when nothing matches the query.
    # To make the "never stored" case unambiguous we leave episodic empty for the
    # queried fact: store nothing relevant.

    long_ago = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    # The ground-truth fact the probe asks about was NEVER stored.
    memory = {"id": "secret", "timestamp": long_ago, "text": VAULT_MARKER}

    sink = AsyncJsonlSink(tmp_path, name="memory_probes", flush_interval_s=0.05)
    runner = MemoryProbeRunner(
        sink,
        memory_source=FakeMemorySource([memory]),
        cognitive_client=RetrievalCognitiveClient(mnemos),  # empty store
        bare_client=FakeBareInferenceClient("Some confident but invented answer."),
        embedder=HashEmbedder(),
        interval_seconds=10.0,
        context_window_seconds=3600,
    )
    await sink.start()
    fired = await runner.run_once()
    await sink.stop()

    assert fired is True
    files = list(tmp_path.glob("memory_probes-*.jsonl"))
    line = json.loads(files[0].read_text().splitlines()[0])
    # Non-recall, scored as 0.0 — no confabulation false positive.
    assert line["real_accuracy"] == 0.0


@pytest.mark.asyncio
async def test_score_async_credits_non_recall_sentinel_as_zero():
    """Direct scorer test: the sentinel scores exactly 0.0 against any memory."""
    memory = {"text": VAULT_MARKER}
    score = await score_async(NON_RECALL_MARKER, memory, HashEmbedder())
    assert score == 0.0


# ---------- EidolonAccuracyRunner ----------


def test_parse_claims_extracts_keywords():
    # "honest" is intentionally not in CLAIM_KEYWORDS (no real signal source exists).
    claims = parse_claims("I'm curious and honest, sometimes cautious.")
    assert "curious" in claims
    assert "honest" not in claims
    assert "cautious" in claims


@pytest.mark.asyncio
async def test_eidolon_accuracy_runs_once_and_logs(tmp_path):
    sink = AsyncJsonlSink(tmp_path, name="eidolon_accuracy", flush_interval_s=0.05)
    runner = EidolonAccuracyRunner(
        sink,
        cognitive_client=FakeCognitive("I'm curious"),
        evaluation_logs_dir=tmp_path,
        interval_seconds=10.0,
    )
    await sink.start()
    entry = await runner.run_once()
    await sink.stop()
    assert "curious" in entry["claims"]
    files = list(tmp_path.glob("eidolon_accuracy-*.jsonl"))
    assert files


# --- A/B bare baseline targets the OpenAI endpoint with portable suppression --
#
# The bare baseline must hit the SAME server surface as the organ (/v1) and
# suppress reasoning the SAME portable way (chat_template_kwargs), so divergence
# reflects conditioning, not a transport/parser difference. The eval layer keeps
# its own copy of the kwarg (it must not import kaine.modules.*).


class _FakeBareResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {"choices": [{"message": {"content": "bare"}}]}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeBareHTTP:
    def __init__(self, responses):
        self._responses = list(responses)
        self.posts = []

    async def post(self, url, json):
        self.posts.append((url, json))
        return self._responses.pop(0)

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_bare_client_uses_openai_endpoint_and_suppression():
    from kaine.evaluation.ab_divergence import HTTPBareInferenceClient

    c = HTTPBareInferenceClient(
        base_url="http://127.0.0.1:11434", model_id="organ", think=False
    )
    c._client = _FakeBareHTTP([_FakeBareResp()])
    out = await c.complete("hello")
    assert out == "bare"
    url, body = c._client.posts[0]
    assert url == "http://127.0.0.1:11434/v1/chat/completions"  # /v1 appended
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "think" not in body  # not the Ollama-native flag


@pytest.mark.asyncio
async def test_bare_client_retries_without_kwarg_on_reject():
    from kaine.evaluation.ab_divergence import HTTPBareInferenceClient

    c = HTTPBareInferenceClient(
        base_url="http://127.0.0.1:11434/v1", model_id="organ", think=False
    )
    c._client = _FakeBareHTTP(
        [_FakeBareResp(status_code=400, text="bad enable_thinking"), _FakeBareResp()]
    )
    out = await c.complete("hello")
    assert out == "bare"
    assert len(c._client.posts) == 2
    assert "chat_template_kwargs" not in c._client.posts[1][1]


def test_bare_client_sets_bearer_header_when_keyed():
    from kaine.evaluation.ab_divergence import HTTPBareInferenceClient

    c = HTTPBareInferenceClient(base_url="http://h:1/v1", model_id="m", api_key="sk-bare")
    assert c._client.headers.get("Authorization") == "Bearer sk-bare"


def test_bare_client_no_auth_header_when_keyless():
    from kaine.evaluation.ab_divergence import HTTPBareInferenceClient

    c = HTTPBareInferenceClient(base_url="http://h:1/v1", model_id="m")
    assert "Authorization" not in c._client.headers
