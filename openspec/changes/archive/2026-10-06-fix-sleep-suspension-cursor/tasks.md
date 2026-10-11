## 1. Bus

- [x] 1.1 `read_entries`, `read` and `read_entries_block` raise `ValueError` for a non-blocking `"$"` cursor, naming the stream and `last_entry_id`. Tests: each method refuses; a blocking read from `"$"` still works.

## 2. Consumers

- [x] 2.1 Chronos and Topos seed their `hypnos.out` cursor from `bus.last_entry_id` in `initialize`.
- [x] 2.2 Audition uses `bus.last_entry_id` in place of its private tail helper.
- [x] 2.3 Real-bus tests per consumer: a published `hypnos.sleep.started` suspends the forward model, and `hypnos.sleep.completed` resumes it. Each test is mutation-checked.
- [x] 2.4 A guard test builds every configurable module with the revive-test doubles on a spied fake bus, runs its loops, and fails if any module reads from `"$"` without blocking (integrator request). It is mutation-checked against Chronos, Topos and Eidolon.

## 3. Validation

- [x] 3.1 `openspec validate fix-sleep-suspension-cursor --strict`.
