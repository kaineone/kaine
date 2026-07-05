## ADDED Requirements

### Requirement: A deterministic perceptual feed supplies reproducible stimulus

The system SHALL provide a deterministic perceptual feed, selectable via
`[topos.perception_feed].mode`, that plugs into the existing Topos `_VideoSource`
seam and supplies a reproducible, copyright-free stimulus stream for research runs.
Two modes SHALL be available: a **seeded procedural** source (the in-repo default,
needing no external media) and a **playlist** source over operator-supplied media
pinned by a checksummed manifest. The feed SHALL ship `mode = "off"` so first boot
is unchanged, and SHALL NOT require live human or live camera input for a research
run.

#### Scenario: Shipped config ships the feed off

- **WHEN** an operator inspects shipped `config/kaine.toml`
- **THEN** `[topos.perception_feed].mode = "off"` and the all-off first-boot guard
  still passes

#### Scenario: A research run selects a deterministic mode

- **WHEN** a research boot sets `mode = "seeded"` or `mode = "playlist"`
- **THEN** Topos receives frames from the corresponding deterministic source via the
  `_VideoSource` seam, with no live human input in the loop

### Requirement: The seeded source is reproducible yet not entity-predictable

The seeded procedural source SHALL generate each frame as a pure function of
`(seed, frame_index)`, so re-running with the same seed yields a bit-identical
stream. It SHALL combine a structured base signal that the world model can learn to
predict with surprise events whose onset and content are drawn from a counter-based
PRNG keyed on the seed. The surprise schedule SHALL be reproducible given the seed
but SHALL NOT be predictable to the entity from the observed frames (anticipating it
would require inverting the keyed PRNG).

#### Scenario: Same seed reproduces the stream

- **WHEN** the seeded source runs twice with the same seed
- **THEN** the frame at any given index is identical across both runs

#### Scenario: Surprise is seed-determined, not frame-derivable

- **WHEN** the seeded source emits surprise events
- **THEN** their schedule is fixed by the seed (reproducible) and is not derivable
  from the observed frame stream without the seed

#### Scenario: Different seeds decorrelate

- **WHEN** two different seeds are used
- **THEN** their surprise schedules are decorrelated (not the same sequence shifted)

### Requirement: The playlist source verifies media for reproducibility

The playlist source SHALL read an operator-supplied manifest listing each media
item's path, sha256 digest, frame rate, and order, and SHALL verify every digest
before a run. A digest mismatch SHALL fail the source (a changed file voids
reproducibility). Item order and frame rate SHALL define a stable frame index across
runs.

#### Scenario: A verified manifest indexes deterministically

- **WHEN** every item's sha256 matches the manifest
- **THEN** the source opens and frame index i maps to the same media frame across
  runs

#### Scenario: A changed file fails closed

- **WHEN** any item's sha256 does not match the manifest
- **THEN** the source fails to open and the run does not proceed on unverified media

### Requirement: Raw frames are never persisted by either source

The deterministic feed SHALL preserve the zero-persistence invariant: neither source
writes raw frames to disk. The seeded source SHALL persist only its seed and
schedule; the playlist source SHALL persist nothing beyond the manifest it is given.
The existing build-time guard against frame-writing calls SHALL continue to cover the
new sources.

#### Scenario: No raw frame is written

- **WHEN** either deterministic source produces frames for Topos
- **THEN** no raw frame is persisted to disk, and only the seed/schedule (seeded) or
  the manifest (playlist) describe the stream

### Requirement: The perceptual stimulus is recorded as a research covariate

The system SHALL record the active feed's reproducible descriptor in the research
submission manifest: for the seeded mode the seed and schedule parameters, and for
the playlist mode the manifest checksum and per-item digests. The descriptor SHALL
be sufficient to regenerate (seeded) or verify (playlist) the exact perceptual input
of the run.

#### Scenario: Seeded descriptor is recorded

- **WHEN** a run uses the seeded source
- **THEN** the submission manifest records the seed and schedule parameters

#### Scenario: Playlist descriptor is recorded

- **WHEN** a run uses the playlist source
- **THEN** the submission manifest records the manifest checksum and item digests
