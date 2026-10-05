## MODIFIED Requirements

### Requirement: Novelty habituates repeated payloads
`NoveltyTracker` SHALL return a novelty score in `[0.0, 1.0]` where 1.0
denotes "fingerprint never seen in window" and the score SHALL decrease
monotonically as the same fingerprint is observed within the window.
The window size SHALL be configurable. The fingerprint SHALL be a pure
function of the event's source, type and payload content: vector fields
and numeric lists removed by the privacy filter's vector rule SHALL NOT
contribute, and remaining floats SHALL be quantised to a recorded
resolution, so that novelty measures the recurrence of content rather
than of exact payload bytes.

#### Scenario: First observation is fully novel
- **WHEN** `observe(event)` is called once for an event the tracker has
  never seen
- **THEN** the returned novelty equals 1.0

#### Scenario: Repeated observation reduces novelty
- **WHEN** the same event is observed 10 times in a window of 32
- **THEN** the tenth observation's novelty is strictly less than the
  first

#### Scenario: Float noise does not make content novel
- **WHEN** two events have the same source, type and categorical fields and differ only in floats by less than the recorded resolution or in vector fields
- **THEN** they share a fingerprint, and the second observation's novelty is less than 1.0

#### Scenario: Changed content is novel
- **WHEN** an event differs from every event in the window in a categorical field
- **THEN** its novelty equals 1.0

