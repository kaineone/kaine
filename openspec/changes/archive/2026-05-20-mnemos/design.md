## Context

Phase 3.2 — the second cognition module. Mnemos sits at the
interaction of the bus (everything goes through it) and the
emotional / self-model layers (recall pulls back the affect that was
stored with the memory). We use the safety-over-UX pattern
established for Redis: containerized Qdrant with mandatory API key,
loopback port mapping, single bootstrap script, password mirrored
into `config/secrets.toml`.

Constraints:
- All-local at runtime. Qdrant container, sentence-transformers
  loaded into the venv, no remote calls after the first model
  download.
- Audit posture identical to Redis: API key required on every host.
- The operator already has a native Qdrant on 6333; the KAINE one
  takes 6533 so they coexist.
- CLS separation per `docs/kaine-paper.md` §3.2: short-term,
  episodic (with emotional tags), semantic (consolidated),
  procedural.

Stakeholders: Thymos (will plug an `EmotionalRetriggerHook`
implementation that adjusts its dimensional state on recall), Eidolon
(observes the same workspace broadcasts Mnemos stores; correlates
identity drift against stored memories), Nous (Phase 3.1 emits
beliefs that Mnemos can later associate with the episodes that
produced them).

## Goals / Non-Goals

**Goals:**
- A `Mnemos(BaseModule)` that, on initialize, ensures the four Qdrant
  collections exist; on each `workspace.broadcast` stores a short-term
  memory tagged with the broadcast's content + any affect labels
  present; periodically consolidates overflow short-term entries into
  episodic.
- Public `recall(query_text, k, collection)` API returning matched
  records with their stored payloads (statement, salience, emotion
  tags, timestamp).
- `EmotionalRetriggerHook` protocol that lets Thymos receive recalled
  emotion summaries asynchronously without Mnemos depending on Thymos.
- Backend swappable: `QdrantStorage` default, `InMemoryStorage`
  fallback for tests. SQLite fallback as the future "minimal
  deployment" path (per build prompt) is deferred to its own change.
- Embedder swappable: `SentenceTransformerEmbedder` default
  (`all-MiniLM-L6-v2`, 384-dim), `FakeEmbedder` for tests.

**Non-Goals:**
- SQLite minimal-deployment backend. The protocol leaves room for it;
  the implementation lands later.
- Cross-collection search. Recall takes a single target collection.
- A full Hypnos deep-consolidation pipeline. Mnemos exposes a
  `consolidate_now()` method that the Phase 6 Hypnos module will call;
  Phase 3.2 doesn't run that pipeline by itself.
- Federated / mesh memory replication. Paper §5.2 territory.

## Decisions

**Qdrant on `127.0.0.1:6533`, container name `kaine-qdrant`, API key
required.** Coexists with the operator's native Qdrant. Bootstrap
script mirrors the Redis pattern; reused operator muscle memory.

**Four collections per backend, fixed names.**
`mnemos_short_term`, `mnemos_episodic`, `mnemos_semantic`,
`mnemos_procedural`. Names are configurable but the defaults are
documented in the spec.

**Short-term lives in a deque inside `MnemosCore`, not in Qdrant.**
The build prompt names it "short-term *buffer*" — the in-memory
characterization matches the paper's CLS framing where fast memory
is the hippocampal index. Capacity default 128 entries; when
exceeded, the oldest entry consolidates into episodic.

**`store(text, payload, affect=None, collection="short_term")` is the
write API.** Mnemos embeds the text, attaches the payload + affect to
the point, and writes to the named collection. Short-term writes also
trigger consolidation when at capacity.

**`recall(query_text, k=5, collection="episodic")` is the read API.**
Embeds the query, searches Qdrant for top-k by cosine similarity,
returns a list of `RecalledMemory` dataclasses. Recall invokes the
configured `EmotionalRetriggerHook` with the affect payloads of the
returned memories so Thymos can pick up "this memory came with
sadness, so I feel sadder now."

**`EmotionalRetriggerHook` is a callable, not a bus publisher by
default.** Phase 3.2 ships a no-op default. Phase 4 Thymos can either
register a hook (push) or subscribe to a `mnemos.recall.affect` bus
event (pull). The push surface is shipped now so we don't have to
mod Mnemos to wire Thymos later.

**Recall also publishes a `mnemos.recall` event so the bus carries
the trace.** Diagnostics-only payload (no memory contents), at low
salience by default, elevated when a memory with a strong affect
tag is recalled.

**Background consolidation is opt-in per tick.** Mnemos doesn't run
a separate timer task — `on_workspace` checks short-term capacity
and consolidates immediately if needed. This keeps lifecycle simple
and aligns consolidation with broadcast cadence.

**Embedding device: `select_device("auto")` by default.** The
encoder is small enough that CPU is fine; the operator can pin to
GPU through `[mnemos].device` in `kaine.toml`.

**HF telemetry off.** `HF_HUB_DISABLE_TELEMETRY=1` is set at
embedder load to keep runtime fully local per the no-cloud-runtime
memory.

## Risks / Trade-offs

- **First-time sentence-transformers download requires network.**
  → Setup-time; documented. After download Mnemos runs offline.
- **Qdrant collection schemas can drift across upgrades.** → KAINE
  pins the image to a specific tag. Phase 6 Hypnos handles
  re-encoding through migration steps later.
- **In-memory short-term loses state on restart.** → Acceptable for
  Phase 3.2; durable short-term is a Phase 6 enhancement.
- **A flood of broadcasts overwhelms embedding.** → Embeddings run
  off the asyncio event loop (asyncio.to_thread). Future change can
  batch.
- **`recall` payload returned to the caller contains contents.** →
  Mnemos's own consumers (Lingua, Eidolon) need contents; Nexus
  diagnostics gets only metrics via the `mnemos.recall` event with
  no payload bodies.

## Migration Plan

First implementation. Mnemos is registered in code paths but not
auto-added; first-boot script wires it up.

## Open Questions

- Whether to make the short-term capacity dynamic against Soma's
  wellness (low wellness → more aggressive consolidation). Deferring
  until Phase 4 Thymos pipes affect into the cycle.
- Whether procedural memory should use a different collection schema
  (skill embeddings vs episode embeddings). Phase 3.2 uses the same
  schema everywhere; later changes can split.
