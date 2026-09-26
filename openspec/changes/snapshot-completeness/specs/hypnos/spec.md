## ADDED Requirements

### Requirement: The sleep schedule survives preservation
Hypnos SHALL save its rest schedule as the time remaining until the original and the effective due times, and SHALL restore it against the current process's clock, so a revived entity's next sleep falls where its preserved schedule placed it. Time spent preserved SHALL NOT count toward the next sleep. An overdue schedule SHALL stay overdue after a restore. A snapshot without a saved schedule SHALL start a fresh interval and log that it did; non-finite or inconsistent values SHALL be refused.

#### Scenario: The schedule round-trips across a long gap
- **WHEN** Hypnos has 600 s left until sleep, is preserved, and is revived after a long gap in a new process
- **THEN** its next sleep is due 600 s after the revive

#### Scenario: An old snapshot starts fresh
- **WHEN** Hypnos is restored from a snapshot with no saved schedule
- **THEN** its next sleep is one configured interval away and a log line says the schedule started fresh
