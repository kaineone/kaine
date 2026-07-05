## ADDED Requirements

### Requirement: EmpatheiaObserver skips pairings with absent confidence

`EmpatheiaObserver` SHALL skip any pairing where the audition event carries
no `confidence` field and SHALL write no record to the sink.  Scoring against
a fabricated default SHALL NOT occur because it yields accuracy near 1.0 for
no-op observations.

When `confidence` is present, the written record SHALL include
`"confidence_present": true`.

#### Scenario: Audition event without confidence — no record written

- **WHEN** an `audition.emotion` event payload lacks a `confidence` key
- **AND** a pending empatheia prediction exists for any agent
- **THEN** `EmpatheiaObserver` SHALL write no record to the sink

#### Scenario: Audition event with confidence — record written with disclosure

- **WHEN** an `audition.emotion` event payload carries a `confidence` float
- **AND** a pending empatheia prediction exists for any agent
- **THEN** `EmpatheiaObserver` SHALL write a record to the sink
- **AND** the record SHALL include `"confidence_present": true`
- **AND** the record SHALL include `"observed_confidence"` equal to the
  event's confidence value
