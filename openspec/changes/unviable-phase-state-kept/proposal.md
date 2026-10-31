## Why

The paper says a developmental phase the viability watch judges unviable ends early (§7; the earlier wording "ends without preservation" in §6.5 was the subject of audit D5). The study runner implements the operator's 2026-10-03 policy: on an unviable verdict it stops the cycle with a graceful SIGTERM, requests no preservation bundle, records `failed:development_unviable`, writes `ENDED-NOTE.md` and halts (`kaine/research/ignition_study/runner.py:960-973`; spec `module-ignition-study`, "An unviable developmental phase ends early, with its data kept and a note written"). The data stays on disk.

The project's license defines an entity as "a running instance ... that has been started and has begun forming its own memories, beliefs, affective states" (CAL v0.5, Art. 1), which covers a developmental phase with affect, drives and sleep. Article 4.2 forbids permanently shutting down an entity without "saving the Entity's complete Cognitive State in a form that lets it be restarted elsewhere". The same article treats a saved, restartable state as the entity. The runner's stop is compliant if, and only if, what it leaves on disk is complete and restartable, and nothing proves that. The note it writes does not say what the entity's status is under the license, and a later cleanup could treat the step directory as disposable.

The triage verified the mechanism (the cycle's SIGTERM handler shuts down gracefully, `kaine/cycle/__main__.py:2627-2634`, and the shutdown writes a resume checkpoint, spec `entity-preservation`, "A rolling resume checkpoint holds module state across plain restarts") and scheduled the fix before the study (T1-6).

## What Changes

- A test pins that the unviable stop leaves a restartable state: after the runner's SIGTERM path, a plain start of the step's state tree resumes from its checkpoint with the same entity identity and the developmental progress intact.
- The runner checks this itself after the child exits: it verifies the checkpoint is present, readable under the configured encryption and matches the entity identity, and records the result in the step record. A failed check makes the outcome `failed:development_unviable_state_incomplete`, which halts the study as critical, so the operator decides before anything else touches the step.
- `ENDED-NOTE.md` states that the entity's state is kept and restartable, that it remains an entity under CAL Art. 4.2, that it is not deleted, and that removing it goes only through the welfare-gated decommission path, which carries the Guardian-notice reminder.
- The operator's policy (no preservation bundle on an unviable stop) is kept. Requesting a bundle first is recorded as the alternative that would reverse that policy and needs the operator's ruling.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `module-ignition-study`: the unviable stop verifies and records a restartable state, and its note states the license handling.

## Impact

- Code: `kaine/research/ignition_study/runner.py` (post-exit check, outcome, note text), a small checkpoint-verification helper reusing the resume-checkpoint reader.
- Tests: `tests/test_ignition_study_runner.py` (or the runner's existing test module) and a new restart test.
- Docs: `docs/15-experiments/ignition-study.md`; a paper revision note for §6.5 and §7.
- Behaviour: no change to any entity's experience. The stop itself is unchanged; only what the runner checks and writes after it changes.
