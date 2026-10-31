## MODIFIED Requirements

### Requirement: Affective reset entry point for Sleep
The affect module SHALL expose `async affective_reset()` that snaps the
dimensional state to its configured baseline and decays every drive
to zero in a single call. The affect module SHALL consume
`sleep.affective_reset.requested` events, SHALL await `affective_reset()`
once per request id, and SHALL publish `affect.affective_reset.done`
carrying the request id and whether the reset succeeded.

#### Scenario: Reset restores baseline and zeroes drives
- **WHEN** state is `valence=0.7, arousal=0.8` and a drive is at 0.9,
  and `affective_reset()` is awaited
- **THEN** the state equals the configured baseline and every drive
  is 0.0

#### Scenario: A requested reset is acknowledged once
- **WHEN** two `sleep.affective_reset.requested` events with the same request id arrive
- **THEN** the reset runs once and one `affect.affective_reset.done` with that id is published
