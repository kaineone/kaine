## ADDED Requirements

### Requirement: Ignition records carry the session and the pass
In a development run each ignition log record SHALL carry the session index and the pass index. Both SHALL be taken in-process at the cycle layer, like the programme position, and SHALL NOT be added to the broadcast, published on the bus, or delivered to any module. The record SHALL still contain no event payloads.

#### Scenario: A broadcast in the third pass
- **WHEN** a coalition is broadcast during pass 3 of session 2
- **THEN** its record holds session 2 and pass 3, and the broadcast published on the bus is identical to the one published with the log disabled
