## MODIFIED Requirements

### Requirement: Five-phase sleep pipeline runs in fixed order
The sleep module SHALL expose `async enter_sleep()` that runs five phases in the order
the paper gives (§3.5): light consolidation, deep consolidation (memory replay
then synaptic downscaling), associative replay, voice alignment, and the
affective reset. The affective reset SHALL be the last phase, so that sleep
ends with it, and `hypnos.sleep.completed` SHALL follow it. The affective reset
SHALL run exactly once even when an earlier phase raises or the sleep is
cancelled, and a second cancel SHALL NOT interrupt it. On any exception,
including a cancel, the sleep module SHALL publish an aborted `hypnos.sleep.completed`
and re-raise the exception. Each phase SHALL
return a `PhaseResult` carrying `phase` name, `success` bool, `elapsed_ms`, and
`error` (None on success). A failure in any one phase SHALL be logged and SHALL
NOT prevent later phases from running.

#### Scenario: All five phases ran in order
- **WHEN** `Hypnos.enter_sleep()` is awaited against fake collaborators
- **THEN** the published `hypnos.sleep.completed` event's `phases` payload
  lists `light_consolidation`, `deep_consolidation`, `associative_replay`,
  `voice_alignment`, `affective_reset`, in that order

#### Scenario: One phase failing does not stop the others
- **WHEN** the episodic memory module's consolidation phase raises during `enter_sleep()`
- **THEN** all four subsequent phases still execute and the completion event
  records `success == False` for light consolidation but `success == True` for
  the others (assuming they succeeded)

#### Scenario: A cancelled sleep still ends with the affective reset
- **WHEN** the task running `enter_sleep()` is cancelled during phase 1, during
  phase 2's replay, or during voice alignment
- **THEN** the affective reset runs once, an aborted `hypnos.sleep.completed`
  with reason `CancelledError` is published, the replay window is closed, and
  the CancelledError propagates

#### Scenario: A second cancel does not interrupt the reset
- **WHEN** a second cancel arrives while the final affective reset is running
- **THEN** the CancelledError propagates and the reset still completes
