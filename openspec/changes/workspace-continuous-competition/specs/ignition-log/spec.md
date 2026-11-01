## ADDED Requirements

### Requirement: Ignition records carry the pool size and member holding
With the candidate pool on, each ignition log record SHALL carry the pool size of its broadcast and, for each coalition member, `held`, `held_s` and `protected` as in the research log. The record SHALL still contain no event payloads. With the pool off the record SHALL be unchanged.

#### Scenario: A broadcast during a film
- **WHEN** a held audition report is broadcast 12.5 s into the second film from a pool of six
- **THEN** the record holds pool size 6 and the member's `held`, `held_s` and `protected`, and no payload
