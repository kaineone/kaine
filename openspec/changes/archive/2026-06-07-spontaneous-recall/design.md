## Context

`Mnemos.on_workspace(snapshot)` serializes the conscious snapshot and stores it
(`_core.store(... collection="short_term")`). `Mnemos.recall(query_text, k,
collection)` embeds the query, retrieves the top-k, and publishes a
`mnemos.recall` event; Thymos consumes `mnemos.recall` to nudge arousal. The
retrieval machinery is complete — only the *trigger* in the live loop is
missing.

## Goals / Non-Goals

**Goals:** the current conscious content cues retrieval of related prior
memories, which re-enter the workspace and reach affect — closing the
store→recall→inform loop, throttled to avoid storms.

**Non-Goals:** no change to embedding, storage, the `recall()`/publish path, or
Thymos. Not building associative spreading activation or goal-directed query
construction — v1 uses the snapshot serialization as the cue. Not gating recall
on inhibition (recall is cognition, not an outward action).

## Decisions

- **Trigger lives in `on_workspace`, recall-before-store.** Mnemos already
  consumes the broadcast there. Recall using the new cue runs *before* the
  store, so the top match is a *prior* related memory, not the identical
  snapshot we are about to store this tick. Store then proceeds unchanged.
- **Cue = the snapshot serialization** (the same text Mnemos would store),
  reusing `_serialize_snapshot`. If it is empty, skip recall (no meaningful
  cue). v1 keeps the cue simple; a future change can build richer queries.
- **Throttle with a cooldown**, not every-tick recall. A `recall_cooldown_s`
  (monotonic-clock) gate ensures recall fires at most once per window, so a
  fast cycle does not spam retrieval or oscillate with the `mnemos.recall`→
  Thymos→workspace path. Storing still happens every tick (unchanged).
- **Recall is NOT inhibition-gated.** Per the executive-action design, only
  outward actions (speech via Lingua, effectors via Praxis) are gated by
  `snapshot.inhibited`. Recall is internal memory dynamics, like storing —
  it runs regardless of inhibition, so the entity can "be reminded" even when
  it has decided to stay silent.
- **No feedback storm with Thymos.** `mnemos.recall` nudges Thymos arousal;
  arousal feeds salience; that could re-trigger recall. The cooldown plus the
  recall-before-store ordering (cue is the current snapshot, not the recall
  event itself) bound this; recall events are not themselves treated as cues.

## Risks / Trade-offs

- [Retrieval cost every cooldown window] → small top-k retrieval; cooldown
  bounds frequency; CPU embedder per config. Acceptable.
- [Cue quality is coarse (whole-snapshot text)] → acceptable for v1 and
  improvable later; the loop existing at all is the point, and the cue is the
  same signal already proven to embed/store.

## Migration Plan

Additive; extends `on_workspace`. Default on via `recall_on_workspace`. Rollback
= revert the branch (Mnemos returns to store-only). No data migration; validated
with fakes, no live boot.

## Open Questions

- Which collection should recall query (short_term vs a longer-term/semantic
  store)? v1: the default `recall()` collection; revisit when semantic
  consolidation matures.
- Should the cue weight the most-salient selected event rather than the whole
  snapshot? Deferred — keep the proven serialization for v1.
