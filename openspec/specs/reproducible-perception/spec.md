# reproducible-perception Specification

## Purpose
TBD - created by archiving change reproducible-perception-feed. Update Purpose after archive.
## Requirements
### Requirement: A deterministic perceptual feed supplies reproducible stimulus

The system SHALL provide a deterministic perceptual feed, selected via a single
shared `[perception_feed].mode`, that supplies a reproducible, copyright-free
stimulus stream to **both** the Topos vision surface (via its `_VideoSource` seam)
and the Audition hearing surface (via its `_AudioStream` `stream_factory` seam).
Two deterministic modes SHALL be available: a **seeded procedural** source (the
in-repo default, needing no external media) and a **playlist** source over
operator-supplied media pinned by a checksummed manifest. The feed SHALL ship
`mode = "off"` so first boot is unchanged and the all-off first-boot guard still
passes, and SHALL NOT require live human, live camera, or live microphone input
for a research run.

#### Scenario: Shipped config ships the feed off

- **WHEN** an operator inspects shipped `config/kaine.toml`
- **THEN** `[perception_feed].mode = "off"` and the all-off first-boot guard still
  passes

#### Scenario: A research run selects a deterministic mode

- **WHEN** a research boot sets `mode = "seeded"` or `mode = "playlist"`
- **THEN** Topos receives frames from the corresponding deterministic video source
  and Audition receives audio from the corresponding deterministic audio source,
  with no live human input in the loop

### Requirement: The seeded source is reproducible yet not entity-predictable

The seeded procedural source SHALL generate each video frame and each audio block
as a pure function of `(seed, frame_index)`, so re-running with the same seed
yields a bit-identical stream. Both the structured base signal (which the world
model can learn to predict) and the surprise events SHALL be keyed on the seed, so
that different seeds produce genuinely different — not merely surprise-shifted —
base worlds. Surprise onset and content SHALL be drawn from a counter-based PRNG
keyed on the seed: reproducible given the seed, but NOT predictable to the entity
from the observed stimulus (anticipating it would require inverting the keyed
PRNG).

#### Scenario: Same seed reproduces the stream

- **WHEN** the seeded source runs twice with the same seed
- **THEN** the video frame and audio block at any given index are identical across
  both runs

#### Scenario: Different seeds produce different base worlds

- **WHEN** two different seeds are used
- **THEN** the base signal — not only the surprise schedule — differs between
  them, so a substantial fraction of frames/blocks differ

#### Scenario: Surprise is seed-determined, not stimulus-derivable

- **WHEN** the seeded source emits surprise events
- **THEN** their schedule is fixed by the seed (reproducible) and is not derivable
  from the observed stimulus without the seed

### Requirement: The playlist source verifies media for reproducibility

The playlist source SHALL read one operator-supplied manifest listing each media
item's path, sha256 digest, frame rate, and order, and SHALL verify every digest
before a run. The same manifest SHALL drive both the video and the audio surface,
so picture and sound come from the same media. A digest mismatch SHALL fail the
source for both surfaces (a changed file voids reproducibility). Item order and
frame rate SHALL define a stable index across runs.

#### Scenario: A verified manifest indexes deterministically

- **WHEN** every item's sha256 matches the manifest
- **THEN** the source opens and index i maps to the same media frame and audio
  position across runs

#### Scenario: A changed file fails closed

- **WHEN** any item's sha256 does not match the manifest
- **THEN** neither the video nor the audio source opens and the run does not
  proceed on unverified media

### Requirement: Raw frames are never persisted by either source

The deterministic feed SHALL preserve the zero-persistence invariant: no source
writes raw frames or raw PCM to disk. The seeded sources SHALL persist only their
seed and schedule; the playlist sources SHALL persist nothing beyond the manifest
they are given. The build-time guard against frame- and PCM-writing calls SHALL
cover both the video source module and the new audio source module.

#### Scenario: No raw stimulus is written

- **WHEN** any deterministic source produces frames or audio
- **THEN** no raw frame or raw PCM is persisted to disk, and only the seed/schedule
  (seeded) or the manifest (playlist) describe the stream

### Requirement: The perceptual stimulus is recorded as a research covariate

The system SHALL record the active feed's reproducible descriptor — covering both
surfaces — in the research submission manifest: for the seeded mode the seed plus
the video and audio schedule parameters, and for the playlist mode the single
manifest checksum and per-item digests. The descriptor SHALL be sufficient to
regenerate (seeded) or verify (playlist) the entity's full audio-visual perceptual
input for the run.

#### Scenario: Seeded descriptor is recorded

- **WHEN** a run uses the seeded source
- **THEN** the submission manifest records the seed and both the video and audio
  schedule parameters

#### Scenario: Playlist descriptor is recorded

- **WHEN** a run uses the playlist source
- **THEN** the submission manifest records the one manifest checksum and item
  digests that pin both surfaces

### Requirement: A deterministic auditory feed supplies reproducible sound

The system SHALL supply a deterministic auditory stimulus to Audition through its
`stream_factory` seam, mirroring the video feed. A **seeded procedural audio**
source SHALL synthesize int16 PCM as a pure function of `(seed, frame_index)` —
a learnable base soundscape plus seed-keyed surprise bursts — needing no external
media or decode dependency. A **playlist audio** source SHALL decode the audio
track of the same checksummed manifest media. When the decoder dependency required
for playlist audio is unavailable, the source SHALL fail honestly with an install
hint and SHALL NOT substitute silence or synthetic audio.

#### Scenario: Seeded audio reproduces per seed

- **WHEN** the seeded audio source runs twice with the same seed
- **THEN** the PCM block at any given index is byte-identical across both runs

#### Scenario: Playlist audio decode is unavailable

- **WHEN** `mode = "playlist"` and the audio-decode dependency is not installed
- **THEN** the audio source raises a clear unavailable error with an install hint
  and the run does not proceed on a faked audio stream

### Requirement: One feed drives both vision and hearing coherently

The shared `[perception_feed]` selection SHALL parameterize both surfaces from one
source of truth. In `playlist` mode both surfaces SHALL walk the same ordered,
checksummed manifest. In `seeded` mode both procedural streams SHALL derive from
the same seed and a shared frame clock, and surprise events SHALL fire on shared
cadence slots so a surprise is presented cross-modally (a visual blob and an audio
burst together). The system SHALL document the synchronization guarantee honestly:
coherence at the media/clip level (playlist) or via the shared seed and cadence
(seeded), NOT frame-locked synchronization across the two module loops.

#### Scenario: Seeded surprises are cross-modal

- **WHEN** the seeded feed fires a surprise on a cadence slot
- **THEN** both a visual surprise (in the Topos stream) and an audio surprise (in
  the Audition stream) occur for that slot

#### Scenario: One manifest pins both surfaces

- **WHEN** a playlist run is configured
- **THEN** a single `playlist_manifest` supplies both the video frames and the
  audio track, with no separate audio manifest required

