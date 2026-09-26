# Proposal — `snapshot-completeness`

## Why

The module-ignition study preserves the entity after every viewing and revives it with one more module. Each revive has to bring back the same individual. An audit of the modules' `serialize`/`deserialize` found three places where a revived entity is not the one that was preserved:

- **Thymos goals are not saved.** `serialize()` holds affect, baseline, drives, the last emotion and the familiarity cache, but not the goal ledger. A revived entity has forgotten every goal it held, and goal relevance, which feeds the appraisal, restarts from nothing.
- **The Hypnos schedule is not restored.** `serialize()` writes the rest scheduler's due times, but they are `time.monotonic()` values from the old process, and `deserialize()` ignores them. A revived entity's next sleep is always one full interval after boot, whatever its sleep pressure was when it was preserved.
- **Nous hands its posterior back to the module but not to the engine.** The engine returns its own last posterior when planning times out or crashes. After a revive that fallback is the uniform prior, so the first degraded step reports a uniform belief instead of the preserved one.

Nous has no other belief carry-over to restore: every step infers from the model's prior `D`, before and after a revive. The snapshot is complete with respect to what Nous holds.

## What changes

- Thymos saves and restores its goal ledger: id, description, priority, state, and created and completed times.
- Hypnos saves its schedule as time remaining (to the original and to the effective due time) and restores it against the new process's clock. Time the entity spent preserved does not count toward its next sleep. A snapshot from before this change, holding only process-relative times, starts a fresh schedule and logs that it did.
- Nous restores the preserved posterior into the engine's fallback as well as the module.
- A revive-with-one-more-module test for every module in the study order proves that each captured module's state survives a revive into a registry with one extra module.

## Out of scope

- Phantasia's training and weight persistence ship off. The study profile turns them on and the study runner refuses a step whose preservation did not capture the world model (`module-ignition-study`).

## Impact

- Modified: `kaine/modules/thymos/module.py`, `kaine/modules/thymos/goals.py`, `kaine/modules/hypnos/module.py`, `kaine/modules/hypnos/scheduler.py`, `kaine/modules/nous/module.py`, `kaine/modules/nous/engine.py`.
- Snapshots gain fields; older snapshots still load.
- Goal descriptions are the entity's own intentions, not sense data, so zero raw-sense-data persistence holds.
