## Context

`Lingua._produce(mode, stream, ...)` publishes to the mode-specific stream
(`lingua.external` / `lingua.internal`) with `"type": f"{stream}"`. The comment
there even says it publishes "so subscribers can filter cleanly" — but the type
it emits is the stream name, while subscribers filter on the semantic type. The
producer is the single point of divergence; all consumers and the tests already
agree on `external_speech` / `internal_speech`.

## Goals / Non-Goals

**Goals:** make the producer emit the semantic types the whole system expects;
guarantee with a test that the producer→consumer type contract holds.

**Non-Goals:** not changing stream names (`lingua.external` / `lingua.internal`
stay — Audio Out and Eidolon read the streams by name, unaffected). Not
introducing a global event-type registry (worth considering later; out of scope
here).

## Decisions

- **Map mode → semantic type in `_produce`:** `"type": f"{mode}_speech"` yields
  `external_speech` / `internal_speech` (mode is already `"external"`/
  `"internal"`). Minimal, and it ties the type to the semantic mode rather than
  the transport.
- **Update the `volition` type constants in lockstep.** `OWN_EXTERNAL_SPEECH_TYPE`
  / `OWN_INTERNAL_SPEECH_TYPE` become the semantic types so drive-policy
  channel-keyed guard-clearing matches the real published type. (The default
  policy keys on source `lingua`, so it is unaffected; only the drive policy's
  type-keyed clearing depends on these.)
- **Add a producer-contract test** that constructs a real `Lingua` (fake chat
  client) and asserts `speak()` publishes `type == "external_speech"` and
  `think()` publishes `type == "internal_speech"`. This is the test that was
  missing — it exercises the producer side, not just hand-built consumer events.
- **Correct, don't weaken, the affected tests.** Volition/drive-policy tests
  that built events with the old `lingua.external`/`lingua.internal` type are
  updated to the semantic types — they were encoding the producer's bug; the
  corrected contract is the right assertion.

## Risks / Trade-offs

- [Something else relies on the stream-name-as-type] → grep shows only the
  producer and the (just-added) volition constants used the stream-name form;
  every other reference uses the semantic types. Low risk; the full suite + the
  new contract test confirm.
- [Stream vs type confusion recurs] → the contract test pins it; a future
  event-type registry would prevent recurrence (noted, deferred).

## Migration Plan

Pure code fix, no data migration. Existing well-formed consumers start receiving
speech immediately. Rollback = revert the branch. Validated with fakes; the
entity stays offline.
