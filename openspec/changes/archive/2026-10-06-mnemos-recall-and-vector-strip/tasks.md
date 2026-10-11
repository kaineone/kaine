## 1. Vector strip and content view

- [x] 1.1 Add `strip_vectors(payload)` to `kaine/privacy_filter.py`, the existing vector rule with no content stripping. Test it against `VECTOR_FIELDS`, the 16-item backstop and `VECTOR_EXEMPT_KEYS`.
- [x] 1.2 `_serialize_snapshot` uses the content view (no `tick=`, no entry IDs) over stripped payloads. The raw-perceptual denylist is unchanged.
- [x] 1.3 Test: a winning foveated `topos.report` (three 768-dimension latents) produces memory text with no floats from those vectors, and the stored and evicted entry holds none either.

## 2. Cosine short-term recall

- [x] 2.1 Short-term recall embeds the query and scores entries by cosine, caching each entry's embedding in memory, excluded from `export_state()`. Ties break toward recency.
- [x] 2.2 Tests:
  - with the real torch-free default embedder, a related memory outranks a more recent unrelated one;
  - a second recall embeds only the query;
  - `export_state()` contains no embeddings;
  - storing performs no embedding.

  Mutation-check each one.
- [x] 2.3 Update the hot-path performance test that asserts no embedder calls on the live loop so it pins the new bound instead: no embedding on store, at most one query embedding plus the uncached entries per recall.

## 3. Docs and validation

- [x] 3.1 `docs/09-modules/mnemos.md` describes cosine short-term recall and the vector strip.
- [x] 3.2 `openspec validate mnemos-recall-and-vector-strip --strict`.
