## ADDED Requirements

### Requirement: Sleep opens World model's scenario window around phases 2 and 3
When the world model module is present, the sleep module SHALL open its scenario window through
`open_scenario_window()` before phase 2, whose replay cues the world model module through
`episodic_memory.replay`, and SHALL close it through `close_scenario_window()` in a
`finally` after phase 3, which cues the world model module directly, so the window is
closed after an exception or a cancel in either phase. A world model module
collaborator without these methods SHALL be cued as before.

#### Scenario: A sleep cues World model through the bus
- **WHEN** a real sleep module, an episodic memory module and a world model module share a bus with their peer
  polls running, the short-term buffer holds traces, and `enter_sleep()` runs
- **THEN** the world model module publishes a `world_model.scenario` seeded from each
  replayed trace, and the scenario window is closed after the sleep

#### Scenario: A cancel in phase 2 closes the window
- **WHEN** the sleep is cancelled during phase 2's replay
- **THEN** the world model module's scenario window is closed

### Requirement: Shutdown settles an in-flight sleep and the held tasks
The sleep module's `shutdown()` SHALL stop its background loops, then cancel a sleep
task still in flight and wait for it, so that the sleep ends with the
affective reset and an aborted `sleep.sleep.completed`, and SHALL then wait
for the tasks it holds in `_shielded_tasks`. Each wait SHALL be bounded, and
a task still pending after it SHALL be logged and left.

#### Scenario: Shutdown during a sleep
- **WHEN** `shutdown()` is called while a triggered sleep is in phase 2
- **THEN** the affective reset runs once, an aborted `sleep.sleep.completed`
  with reason `CancelledError` is published, and no held task is pending

#### Scenario: Shutdown waits for a held reset
- **WHEN** `shutdown()` is called while the final affective reset is running
- **THEN** shutdown returns after the reset completes

#### Scenario: The wait is bounded
- **WHEN** a held task does not finish
- **THEN** shutdown returns after the bound and logs the pending task

### Requirement: Sleep shuts down before the other modules
The cycle's shutdown and the supervisor's halt SHALL shut the sleep module down first and the other
modules after it in registration order, so a sleep still in flight ends while
The episodic memory, affect and world model modules are up.

#### Scenario: The reset runs while Affect is up
- **WHEN** the cycle shuts its modules down during a sleep, with the sleep module
  registered after the affect module
- **THEN** the affective reset runs before the affect module shuts down
