## MODIFIED Requirements

### Requirement: Research runs send the running caretaker notices
A research-mode cycle SHALL build the caretaker from the same `[caretaker]` section as an unattended one and SHALL send the same running notices (welfare-protective response, lost stimulus source, lost input, stalled individuation assessment). A welfare response whose freeze cannot be written SHALL send `welfare_freeze_failed` instead of "welfare response fired", and SHALL send `welfare_freeze_placed` once the retried freeze is in place. It SHALL NOT gain any gate condition. An invalid `[caretaker]` section SHALL refuse the boot with a configuration error, and a missing channel SHALL be logged as a warning.

#### Scenario: A research run's welfare response is sent
- **WHEN** the welfare monitor of a research run acts on a crossing
- **THEN** a caretaker notice with the event kind "welfare response fired" is sent

#### Scenario: A research run's welfare freeze cannot be written
- **WHEN** the welfare monitor of a research run acts on a crossing and its welfare freeze cannot be written
- **THEN** a caretaker notice with the event kind `welfare_freeze_failed` is sent instead of "welfare response fired"
- **AND** a caretaker notice with the event kind `welfare_freeze_placed` is sent once the retried freeze is in place

#### Scenario: An operator-present run builds no caretaker
- **WHEN** an operator-present cycle boots
- **THEN** no caretaker is built, as before
