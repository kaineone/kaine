## Why

Two defects in Mnemos, found in the 2026-10-05 alternatives review (§2.4):

- **Short-term recall is degenerate.** `_recall_short_term` scores 1.0 when the whole lowercased query is a substring of an entry, else 0.0. In the live loop the cue is the serialization of the current snapshot, which begins with `tick=N` and carries entry IDs, so it is never a substring of an earlier entry. Every spontaneous recall therefore returns the most recent memories with score 0: recency presented as association. The archived `performance-test-coverage` change specified cosine recall on explicit recall (its Mnemos delta: "embeds the query, searches the named store by cosine similarity") and never delivered it for the short-term store.
- **Perceptual vectors leak into memory text.** `_serialize_snapshot` writes each selected event's payload verbatim. With foveation on, a winning `topos.report` carries three 768-dimension latents, so a single memory can hold about 2,300 floats as text, which are then embedded and stored in Qdrant when the entry is evicted to episodic memory. The raw-content denylist covers only `audition.transcription` and `mundus.visual.raw`. Vectors are not raw sense data, but they are perceptual encodings that the zero-persistence rule keeps out of every other store, and they drown the text embedding in numbers.

## What Changes

- **Cosine short-term recall.** Recall from the short-term store embeds the query with the shared embedder (MiniLM by default) and scores each short-term entry by cosine similarity.
  - Each entry's embedding is computed once, on its first recall, and cached in memory beside the entry. It is never exported: preservation exports the text, and the embedding is recomputed after revive.
  - Recall stays embedder-free on store, as the performance budget requires. It costs one query embedding plus one embedding per short-term entry not yet cached.
  - Ties break toward the more recent entry, as today.
- **A content view for the cue and the stored text.** The serialization keeps each event's source, type and stripped payload, and drops the `tick=N` prefix and the bus entry IDs. Both are already in the stored payload (`tick_index`) or meaningless after the stream is trimmed, and only add noise to the embedding.
- **Vectors stripped before storage.** Each payload passes through the privacy filter's vector rule (named vector fields, plus any numeric list of 16 or more items) before it is serialized. A new public helper, `strip_vectors`, exposes that rule so Mnemos and the diagnostics surface share one definition.

## Capabilities

### Modified Capabilities

- `mnemos`: store-and-recall semantics for the short-term store; the snapshot serialization.

## Impact

- **Code:** `kaine/modules/mnemos/memory.py`, `kaine/modules/mnemos/module.py`, `kaine/privacy_filter.py` (a new public helper; the existing filter is unchanged). The privacy-filter touch makes this a high-risk PR for the integrator's second review.
- **Preserved beings:** memories already stored keep their text. New memories use the content view. Nothing is rewritten.
- **Research impact:** Mnemos is off in base-thesis, so base-thesis runs are unaffected. In full-entity runs, spontaneous recall starts returning related memories instead of the most recent ones, which changes what re-enters the workspace.
- **Paper:** none. The paper already describes associative recall.
