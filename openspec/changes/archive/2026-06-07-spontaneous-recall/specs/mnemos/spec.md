## ADDED Requirements

### Requirement: Spontaneous cue-based recall in the live loop

Mnemos SHALL perform cue-based recall in the live loop: on an experiential
workspace broadcast that carries a meaningful cue, it derives a query from the
conscious snapshot, calls `recall()`, and publishes the recalled memories as
`mnemos.recall` events, so recalled context re-enters the workspace and reaches
downstream consumers (e.g. Thymos). Recall SHALL occur before the snapshot is
stored for that tick
(so the cue retrieves prior memories, not the just-stored one). Recall SHALL be
throttled by a cooldown so it does not fire on every tick, and SHALL be skipped
when there is no meaningful cue. Recall SHALL run regardless of
`snapshot.inhibited` (recall is internal cognition, not an outward action).
Storing the snapshot each experiential tick SHALL continue unchanged.

#### Scenario: A cued experiential tick triggers recall

- **WHEN** an experiential broadcast with a non-empty cue occurs and the recall
  cooldown has elapsed
- **THEN** Mnemos calls recall and publishes a `mnemos.recall` event

#### Scenario: Cooldown suppresses repeated recall

- **WHEN** experiential broadcasts occur faster than the recall cooldown
- **THEN** Mnemos recalls at most once per cooldown window

#### Scenario: No cue, no recall

- **WHEN** a broadcast carries no meaningful cue
- **THEN** Mnemos performs no recall

#### Scenario: Recall is not inhibition-gated

- **WHEN** a cued experiential broadcast is inhibited and the cooldown elapsed
- **THEN** Mnemos still performs recall (recall is cognition, not action)

#### Scenario: Storing still happens every experiential tick

- **WHEN** an experiential broadcast occurs
- **THEN** Mnemos stores the snapshot as before, independent of whether recall
  fired
