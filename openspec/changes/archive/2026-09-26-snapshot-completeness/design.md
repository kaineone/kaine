# Design — `snapshot-completeness`

## Thymos goals

- `GoalLedger.to_dict()` returns `{"goals": [{id, description, priority, state, created_at, completed_at}, ...]}` in insertion order. `GoalLedger.from_dict()` rebuilds the ledger. Invalid entries (a bad state, a priority outside [0, 1], a missing id or description) are dropped and logged; the rest load.
- `ThymosModule.serialize()` adds `"goals": self._goals.to_dict()`. `deserialize()` replaces the ledger when the key is present and leaves it untouched otherwise.
- No `thymos.goal` events are published on restore. A restore is not a lifecycle change.

## Hypnos schedule

- `RestScheduler.export_remaining() -> {"original_due_in": float, "effective_due_in": float}`, both `due_at - now`, which may be negative when sleep is overdue.
- `RestScheduler.restore_remaining(original_due_in, effective_due_in)` sets `original_due_at = now + original_due_in` and `effective_due_at = now + effective_due_in`. It refuses (ValueError) non-finite values, and a negative deferral (`effective_due_in < original_due_in`). An overdue schedule stays overdue, so the revived entity sleeps when it next can.
- `HypnosModule.serialize()` writes `"schedule": export_remaining()` beside the existing keys. `deserialize()` calls `restore_remaining` when `"schedule"` is present. Without it, as in a snapshot from before this change, the schedule stays fresh and Hypnos logs `hypnos: snapshot has no schedule; starting a fresh interval`.
- The preserved span does not count: the remaining time is measured when the snapshot is taken and applied when the revive lands, and the entity is frozen in between.

## Nous

- `PymdpEngine.seed_posterior(posterior)` sets the engine's last posterior when its shape matches the model's factors (one distribution per factor, each the factor's length, finite and non-negative), and ignores it with a warning otherwise. `NousModule` calls it only when the engine has it; the test `FakeEngine` gains it too.
- `NousModule.deserialize()` calls it after restoring `_last_posterior`.

## Tests

- Every module, all sixteen: its snapshot, after a JSON round-trip, restores into a fresh instance and serializes back identically. Configuration echoed into a snapshot follows the current configuration, not the snapshot: Audition's model ids, Vox's voice mode, and Phantasia's backend, checkpoint, persistence and training flags. Those keys are compared against a fresh, identically configured instance instead.
- A study-order chain: starting from the base modules, each step changes every module's state, runs `preserve_live`, builds a new registry with one more module, runs `revive`, and checks that every captured module matches and that the new module equals a fresh one. Eidolon's launch name is random, so it is not compared.
