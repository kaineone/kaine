## Context

Hypnos publishes `hypnos.sleep.started` / `hypnos.sleep.completed` (spec-mandated,
producer-correct, covered by `test_hypnos_module.py`). Three consumers filter on
types Hypnos never emits (`hypnos.began_rest` / `hypnos.ended_rest` in
`sleep_snapshots.py` + `conversation.py`; `hypnos.cycle_complete` in
`voice_tracking.py`). Their tests construct events with those wrong types, so
they pass while the live path is dead — the same producer/consumer contract gap
as the Lingua speech-type fix.

## Goals / Non-Goals

**Goals:** the three consumers filter on the canonical Hypnos types so they
receive the lifecycle events live; tests exercise the real contract.

**Non-Goals:** no change to Hypnos (producer is correct per spec). Not renaming
the canonical types. Not building a global event-type registry (recommended
separately; would prevent this whole class structurally).

## Decisions

- **Fix the consumers, not the producer.** The hypnos spec is authoritative
  (`hypnos.sleep.started`/`.completed`); the producer and its tests already
  match. So the consumers are corrected: `began_rest` → `hypnos.sleep.started`,
  `ended_rest` and `cycle_complete` → `hypnos.sleep.completed`.
- **`cycle_complete` and `ended_rest` both map to `hypnos.sleep.completed`.**
  Voice tracking keyed on a completion event; the canonical completion event is
  `hypnos.sleep.completed`, which carries the cycle summary the observer needs.
- **Correct the wrong-type tests; they become the regression guard.** The
  evaluation-observer tests that pushed `began_rest`/`ended_rest`/`cycle_complete`
  are updated to the canonical types — now they fail if a consumer regresses.
  Add a conversation test that `hypnos.sleep.started` → sleeping and
  `hypnos.sleep.completed` → awake.

## Risks / Trade-offs

- [Another consumer relies on the old names] → the exhaustive grep found exactly
  these three consumers + their tests; nothing else uses the old names. Full
  suite confirms.
- [The deeper cause recurs elsewhere] → a canonical event-type registry would
  prevent it structurally; flagged as a follow-up, out of scope here.

## Migration Plan

Pure consumer-side string fix. Rollback = revert the branch. No data migration;
validated with fakes, entity stays offline.
