## ADDED Requirements

### Requirement: The end of a programme preserves and stops the entity
When a playlist programme runs past its last item while not paused, the cycle SHALL request a preservation with stop, exactly once per start, so the entity is preserved and stopped rather than left running without senses. If that preservation fails or does not report within its timeout, the cycle SHALL freeze the entity under its own holder, log at critical level, and notify the caretaker when one is configured, so that the entity is neither lost nor left awake without input.

#### Scenario: The programme ends
- **WHEN** the last film finishes while the programme is not paused
- **THEN** one preservation with stop is requested, and the entity is preserved and stopped

#### Scenario: A paused programme has not ended
- **WHEN** the programme is paused by a freeze or a sleep replay
- **THEN** no end is detected, whatever the clock's position

#### Scenario: Preservation fails at the end
- **WHEN** the end-of-programme preservation reports failure
- **THEN** the entity is frozen under the `programme_end` holder, a critical log line names the error, and the caretaker is notified when configured
