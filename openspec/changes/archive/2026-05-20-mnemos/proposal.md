## Why

`docs/kaine-paper.md` §3.2 places Mnemos as the memory module
implementing Complementary Learning Systems (CLS, McClelland et al.
1995): short-term, episodic with emotional tags, semantic
(consolidated), procedural. Build prompt §3.2 names Qdrant as the
vector backend ("Deploy Qdrant in a container for vector memory") and
the SQLite fallback for minimal deployments.

Mnemos is the second Phase 3 piece. Nous reasons; Mnemos remembers;
Eidolon observes patterns over both. The episodic store with emotional
tags is what enables Phase 4 Thymos's emotional re-triggering on
recall — a memory's stored affect comes back as ambient affect when
the memory comes back.

## What Changes

- Add `compose/qdrant.yml`: containerized Qdrant on `127.0.0.1:6533`
  (avoids the operator's pre-existing native Qdrant on 6333), API key
  mandatory via `${KAINE_QDRANT_API_KEY:?...}`. Named volume,
  loopback-only port mapping, restart unless-stopped, healthcheck via
  REST `/readyz`. Same safe-by-default posture as the Redis container.
- Add `scripts/qdrant-bootstrap.sh` mirroring
  `scripts/redis-bootstrap.sh`: generates a strong key, writes
  `compose/.env`'s `KAINE_QDRANT_API_KEY=...` line atomically,
  mirrors into `config/secrets.toml`'s `[qdrant].api_key`, recreates
  the container, confirms `/readyz`.
- Add `kaine.modules.mnemos` package split across files:
  - `embeddings.py` — `Embedder` protocol + `SentenceTransformerEmbedder`
    default loading `sentence-transformers/all-MiniLM-L6-v2` (384-dim,
    Apache-2.0, ~80 MB cached). Lazy import; `select_device`-aware.
  - `storage.py` — `MemoryStorage` protocol + `QdrantStorage`
    backed by the containerized Qdrant. `InMemoryStorage` fallback
    for tests and minimal deployments. Each backend manages four
    collections: `short_term`, `episodic`, `semantic`, `procedural`.
  - `memory.py` — `MnemosCore` orchestration: store (with emotional
    tags), recall (top-k by cosine similarity), consolidate
    (short-term → episodic when capacity reached), and an
    `EmotionalRetriggerHook` callable invoked on recall so Thymos
    can pick up the affective fingerprint of recalled memories.
  - `module.py` — `Mnemos(BaseModule)` subscribing to
    `workspace.broadcast`. Every broadcast becomes a stored
    short-term memory; background consolidation moves overflow into
    episodic.
- Add `qdrant-client>=1.7,<2` and `sentence-transformers>=2.7,<6` to
  `pyproject.toml` (the wide upper bound covers the 5.x line that
  shipped recently).
- `[mnemos]` block in `config/kaine.toml`: backend (`qdrant` |
  `inmemory`), collection names, short-term capacity, consolidation
  threshold, embedder model id, device preference, `recall_top_k`
  default, baseline/alert salience for recall events.
- Tests use `InMemoryStorage` + a `FakeEmbedder` so the suite runs
  without Qdrant or the sentence-transformers download. One opt-in
  test loads the real embedder.

## Capabilities

### New Capabilities

- `mnemos`: CLS-separated memory with four stores (short-term in
  process, episodic / semantic / procedural in Qdrant), text-vector
  embedding, top-k cosine recall, emotional re-triggering hook for
  Thymos, background consolidation, Hypnos-time deep consolidation
  hook.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus`, `module-pattern`, `dynamic-hardware`.
  All shipped.
- **Repo:** adds `compose/qdrant.yml`, `scripts/qdrant-bootstrap.sh`,
  `kaine/modules/mnemos/*.py`, `tests/test_mnemos_*`, updates
  `pyproject.toml`, `config/kaine.toml`, `compose/.env.example` (new
  `KAINE_QDRANT_API_KEY=` line, commented placeholder),
  `config/secrets.example.toml` (new `[qdrant]` block),
  `DEPENDENCIES.md`.
- **Operator actions:** the same one-command pattern as Redis —
  `bash scripts/qdrant-bootstrap.sh` brings up the container with
  auth, mirrors the key into secrets.
- **Disk:** the sentence-transformers model is ~80 MB cached in
  HF on first use. Qdrant image ~50 MB. Bus stays on Redis.
- **No runtime impact** on the cycle. Mnemos is registered in code
  paths but not auto-added to ModuleRegistry; first boot decides.
