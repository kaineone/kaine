## ADDED Requirements

### Requirement: Ignition records carry the pool size and member ages
Each ignition log record SHALL carry the pool size of its broadcast and, for each coalition member, `held` and `age_s` as in the research log. The record SHALL still contain no event payloads.

#### Scenario: A broadcast during a film
- **WHEN** a held audition report is broadcast 12.5 s into the second film from a pool of six
- **THEN** the record holds pool size 6 and the member's `held` and `age_s`, and no payload
