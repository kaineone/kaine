## Context

- `2026-06-07-spontaneous-recall` added cue-based recall in the live loop, on the short-term store, cooldown-throttled.
- `2026-09-17-performance-test-coverage` deferred embedding of short-term entries to eviction or recall, so storing stays cheap on the hot path.

## Decisions

### D1. Cache per entry, never persisted

`StoredMemory` gains an optional in-memory embedding field.
- It is filled on first recall.
- It is excluded from `export_state()`.
- It is never written to storage. Eviction to episodic re-embeds the text as today, so the cached embedding is not reused there. Storage owns its own vectors.

### D2. Embedding-space binding

The cache is invalidated if the embedder's model ID changes at runtime. The existing "A memory store is bound to its embedding space" requirement already refuses a mismatched store at boot.

### D3. Cost

The shared embedder runs on CPU. A spontaneous recall costs one query embed plus the uncached entries, at most `short_term_capacity` (128) once per entry lifetime. A hot-path test pins the bound: a second recall with no new entries embeds exactly one text, the query.

### D4. Content view

The stored text becomes `source:type=<stripped payload>` pieces joined by ` | `, prefixed `inhibited` or `active`.
- The raw-perceptual denylist still replaces a denied payload with `<raw-perceptual omitted>`.
- `tick_index` stays in the stored payload.
- Nothing in the codebase parses the old text.

### D5. One vector rule

`strip_vectors(payload)` in `kaine/privacy_filter.py` applies exactly `_scrub(payload, frozenset(), vector_fields=VECTOR_FIELDS)`. It removes vectors and keeps content, because memory content is legitimate cognitive state while vectors are not memory text.
