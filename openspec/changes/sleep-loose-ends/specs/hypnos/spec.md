## ADDED Requirements

### Requirement: Hypnos opens Phantasia's scenario window around phases 2 and 3
When Phantasia is present, Hypnos SHALL open its scenario window through
`open_scenario_window()` before phase 2, whose replay cues Phantasia through
`mnemos.replay`, and SHALL close it through `close_scenario_window()` in a
`finally` after phase 3, which cues Phantasia directly, so the window is
closed after an exception or a cancel in either phase. A Phantasia
collaborator without these methods SHALL be cued as before.

#### Scenario: A sleep cues Phantasia through the bus
- **WHEN** a real Hypnos, Mnemos and Phantasia share a bus with their peer
  polls running, the short-term buffer holds traces, and `enter_sleep()` runs
- **THEN** Phantasia publishes a `phantasia.scenario` seeded from each
  replayed trace, and the scenario window is closed after the sleep

#### Scenario: A cancel in phase 2 closes the window
- **WHEN** the sleep is cancelled during phase 2's replay
- **THEN** Phantasia's scenario window is closed

### Requirement: Shutdown settles an in-flight sleep and the held tasks
Hypnos's `shutdown()` SHALL stop its background loops, then cancel a sleep
task still in flight and wait for it, so that the sleep ends with the
affective reset and an aborted `hypnos.sleep.completed`, and SHALL then wait
for the tasks it holds in `_shielded_tasks`. Each wait SHALL be bounded, and
a task still pending after it SHALL be logged and left.

#### Scenario: Shutdown during a sleep
- **WHEN** `shutdown()` is called while a triggered sleep is in phase 2
- **THEN** the affective reset runs once, an aborted `hypnos.sleep.completed`
  with reason `CancelledError` is published, and no held task is pending

#### Scenario: Shutdown waits for a held reset
- **WHEN** `shutdown()` is called while the final affective reset is running
- **THEN** shutdown returns after the reset completes

#### Scenario: The wait is bounded
- **WHEN** a held task does not finish
- **THEN** shutdown returns after the bound and logs the pending task
