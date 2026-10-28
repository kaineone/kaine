## ADDED Requirements

### Requirement: Research runs send the running caretaker notices
A research-mode cycle SHALL build the caretaker from the same `[caretaker]` section as an unattended one and SHALL send the same running notices (welfare-protective response, lost stimulus source, lost input, stalled individuation assessment). It SHALL NOT gain any gate condition. An invalid `[caretaker]` section SHALL refuse the boot with a configuration error, and a missing channel SHALL be logged as a warning.

#### Scenario: A research run's welfare response is sent
- **WHEN** the welfare monitor of a research run acts on a crossing
- **THEN** a caretaker notice with the event kind "welfare response fired" is sent

#### Scenario: An operator-present run builds no caretaker
- **WHEN** an operator-present cycle boots
- **THEN** no caretaker is built, as before
