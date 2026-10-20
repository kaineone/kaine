## MODIFIED Requirements

### Requirement: Canonical within-tick event ordering
Before scoring and selection, the cycle SHALL order each tick's gathered events by
a total deterministic key (`source`, `type`, `entry_id`, `stream`), where `entry_id`
is the bus entry id compared as the integer pair (milliseconds, sequence), which is arrival order within a
stream, and `stream` the stream the event was read from, so that selection
tie-breaks do not depend on dispatch incidentals. After ordering, the cycle SHALL name
each event by its stream-qualified key `<stream>:<entry_id>` and hand the workspace those
keys as the candidate ids.

#### Scenario: Tie-break is stable regardless of arrival order
- **WHEN** equal-salience events from different sources are gathered in an arbitrary arrival order
- **THEN** the selection tie-break resolves them in the canonical `(source, type, entry_id, stream)` order

#### Scenario: Entry ids order numerically
- **WHEN** one stream holds twelve events with ids `1760000000000-0` to `1760000000000-11`
- **THEN** the workspace receives them in sequence order, `-2` before `-10`

#### Scenario: Candidate ids carry the stream
- **WHEN** the cycle reads an entry with id `1760000000000-0` from `interoception.out`
- **THEN** the workspace receives it with the id `interoception.out:1760000000000-0`
