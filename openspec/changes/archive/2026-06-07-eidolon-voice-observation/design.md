## Context

`Eidolon._internal_speech_loop` reads `lingua.internal` and only bumps
`internal_speech_count`. `SelfModel` (frozen dataclass, JSON-persisted via
`asdict`/`from_json`) holds values/norms/capability_map/personality_baseline/
identity_history/internal_speech_count. There is no external-speech observation
and no content-derived feature. Lingua now publishes `external_speech` /
`internal_speech` events (after `fix-lingua-speech-event-type`).

## Goals / Non-Goals

**Goals:** Eidolon observes the developing voice across both channels, recording
lightweight features into the self-model so verbosity/frequency trends are
visible over time.

**Non-Goals:** not storing raw utterance text in the persisted self-model
(privacy: derived features only; raw content lives in the intent-expression log
and encryption at rest is deferred). Not changing drift detection to voice-based
(kept source-based for v1; voice-drift is a future change). Not analyzing
semantic/vocabulary content (deferred — can draw on the intent log later).

## Decisions

- **Observe both channels, symmetric loops.** Keep the internal-speech loop;
  add an external-speech loop reading `lingua.external`. Both record a feature
  dict and bump their channel count. Lingua publishes only `external_speech` to
  `lingua.external` and `internal_speech` to `lingua.internal`, so reading the
  stream is sufficient; the loop reads the utterance `text` from the payload to
  compute features, then discards it.
- **Persist features, not text.** Each observation: `{timestamp, channel,
  length, word_count}`. This satisfies "observe the developing voice" (frequency
  + verbosity trend) while keeping the persisted self-model free of raw speech
  content — privacy-conscious given deferred at-rest encryption, and non-
  duplicative of the intent-expression log.
- **Capped rolling buffer**, like `identity_history`: `voice_observations`
  trimmed to `voice_observations_cap` (default e.g. 256). Plus
  `external_speech_count` parallel to `internal_speech_count`.
- **JSON round-trip with defaults.** `from_json` reads the new fields with
  empty/zero defaults so existing persisted self-models load unchanged.

## Risks / Trade-offs

- [Self-model growth] → buffer is capped; features are tiny.
- [Features are coarse vs. true "voice"] → acceptable v1; the loop existing for
  both channels + a trend signal is the gap-closer; richer analysis deferred to
  a change that reads the intent log.
- [Reading text to compute features touches content] → the text is read from the
  event payload to compute length/word_count and then discarded; only features
  are stored or persisted.

## Migration Plan

Additive; new SelfModel fields default empty so old persisted models load fine.
Rollback = revert the branch. Validated with fakes; entity stays offline.

## Open Questions

- Should drift eventually incorporate voice features (verbosity/vocabulary
  drift), per §63's "notices when it is becoming someone different"? Deferred to
  a dedicated voice-drift change.
