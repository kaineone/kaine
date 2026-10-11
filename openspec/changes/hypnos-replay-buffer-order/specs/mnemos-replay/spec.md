## ADDED Requirements

### Requirement: Replay draws on the sleep's consolidated traces
When Hypnos phase 1 moves the short-term buffer into the episodic store,
Mnemos SHALL keep the moved traces, each with the episodic point id it was
stored under, and phase 2's replay SHALL include them among its candidates,
alongside any trace still in the short-term buffer. Each consolidation pass
SHALL replace the kept traces, and Mnemos SHALL drop them when the sleep
completes, so a sleep replays only traces consolidated in that sleep or still
held short-term.

#### Scenario: Phase 2 replays what phase 1 consolidated
- **WHEN** the short-term buffer holds three traces, the replay window is open,
  and phase 1 then phase 2 run
- **THEN** phase 1 moves three traces, phase 2 publishes a `mnemos.replay`
  event for each, and each event's `memory_id` is the trace's episodic point id

#### Scenario: A later sleep does not replay an earlier sleep's traces
- **WHEN** a consolidation pass has moved traces, and a later pass runs with an
  empty short-term buffer
- **THEN** a replay after the later pass finds no candidates and publishes
  nothing
