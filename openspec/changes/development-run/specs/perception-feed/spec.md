## MODIFIED Requirements

### Requirement: The end of a programme preserves and stops the entity
When a playlist programme runs past its last item while not paused, the cycle SHALL request a preservation with stop, exactly once per start, so the entity is preserved and stopped rather than left running without senses. In a development-run session (`[perception_feed].programme_end = "continue"`) the session's playlist is the programmes of its schedule in turn, a pass end is the end of a programme's last item, and the cycle SHALL instead request a preservation without stop at each pass end and, once it reports success, start the next pass at its programme's first item with the pass index incremented, looping to the schedule's first programme after its last, unless a stop request for that pass end is present in the session's control directory, in which case it SHALL request a preservation with stop. If any of these preservations fails or does not report within its timeout, the cycle SHALL freeze the entity under its own holder, log at critical level, and notify the caretaker when one is configured, so that the entity is neither lost nor left awake without input.

#### Scenario: The programme ends
- **WHEN** the last film finishes while the programme is not paused
- **THEN** one preservation with stop is requested, and the entity is preserved and stopped

#### Scenario: A paused programme has not ended
- **WHEN** the programme is paused by a freeze or a sleep replay
- **THEN** no end is detected, whatever the clock's position

#### Scenario: Preservation fails at the end
- **WHEN** the end-of-programme preservation reports failure
- **THEN** the entity is frozen under the `programme_end` holder, a critical log line names the error, and the caretaker is notified when configured

#### Scenario: A pass ends in a development-run session
- **WHEN** `programme_end` is `"continue"`, the last film finishes and no stop request is present
- **THEN** one preservation without stop is requested, and after it reports success the next programme's first item plays as pass n + 1

#### Scenario: A stop is requested for the pass end
- **WHEN** `programme_end` is `"continue"` and the runner placed a stop request before the last film finished
- **THEN** one preservation with stop is requested at the pass end and no next pass starts
