# reproducible-perception (spec delta — DESIGN ONLY)

## MODIFIED Requirements

### Requirement: A deterministic perceptual feed supplies reproducible stimulus

The system SHALL provide a deterministic perceptual feed, selected via a single
shared `[perception_feed].mode`, that supplies a reproducible, copyright-free
stimulus stream to **both** the Topos vision surface (via its `_VideoSource` seam)
and the Audition hearing surface (via its `_AudioStream` `stream_factory` seam).
**Three** deterministic modes SHALL be available: a **seeded procedural** source (the
in-repo default, needing no external media), a **playlist** source over
operator-supplied media pinned by a checksummed manifest, **and a `womb` source that
synthesises a low-complexity gestational stimulus (a low-pass soundscape with an
external maternal heartbeat, and a dim maternal-state-coloured visual field) as a pure
function of `(seed, frame_index)`**. The feed SHALL ship `mode = "off"` so first boot
is unchanged and the all-off first-boot guard still passes, and SHALL NOT require live
human, live camera, or live microphone input for a research run.

#### Scenario: Shipped config ships the feed off

- **WHEN** an operator inspects shipped `config/kaine.toml`
- **THEN** `[perception_feed].mode = "off"` and the all-off first-boot guard still
  passes

#### Scenario: A research run selects a deterministic mode

- **WHEN** a research boot sets `mode = "seeded"`, `mode = "playlist"`, or
  `mode = "womb"`
- **THEN** Topos receives frames from the corresponding deterministic video source
  and Audition receives audio from the corresponding deterministic audio source,
  with no live human input in the loop

#### Scenario: The womb mode is a deterministic, additive third mode

- **WHEN** `mode = "womb"` is selected
- **THEN** the womb video and audio sources drive the two surfaces as pure functions
  of `(seed, frame_index)`, and the `seeded` and `playlist` modes are unchanged

### Requirement: One feed drives both vision and hearing coherently

The shared `[perception_feed]` selection SHALL parameterize both surfaces from one
source of truth. In `playlist` mode both surfaces SHALL walk the same ordered,
checksummed manifest. In `seeded` mode both procedural streams SHALL derive from
the same seed and a shared frame clock, and surprise events SHALL fire on shared
cadence slots so a surprise is presented cross-modally (a visual blob and an audio
burst together). **In `womb` mode both surfaces SHALL derive from the same seed and a
shared frame clock, and the maternal heartbeat SHALL be presented cross-modally — the
audio thud and the visual luminance pulse SHALL share the same beat phase — so the
beat is heard and seen together.** The system SHALL document the synchronization
guarantee honestly: coherence at the media/clip level (playlist) or via the shared
seed and cadence/beat phase (seeded, womb), NOT frame-locked synchronization across
the two module loops.

#### Scenario: Seeded surprises are cross-modal

- **WHEN** the seeded feed fires a surprise on a cadence slot
- **THEN** both a visual surprise (in the Topos stream) and an audio surprise (in
  the Audition stream) occur for that slot

#### Scenario: One manifest pins both surfaces

- **WHEN** a playlist run is configured
- **THEN** a single `playlist_manifest` supplies both the video frames and the
  audio track, with no separate audio manifest required

#### Scenario: The womb heartbeat is cross-modal

- **WHEN** the womb feed emits a maternal heartbeat
- **THEN** the audio thud and the visual luminance pulse occur in phase on the shared
  beat clock, so the beat is heard and seen together

### Requirement: Raw frames are never persisted by either source

The deterministic feed SHALL preserve the zero-persistence invariant: no source
writes raw frames or raw PCM to disk. The seeded sources SHALL persist only their
seed and schedule; the playlist sources SHALL persist nothing beyond the manifest
they are given; **the womb sources SHALL persist only their seed and womb
parameters**. The build-time guard against frame- and PCM-writing calls SHALL cover
the seeded, playlist, **and womb** video and audio source modules.

#### Scenario: No raw stimulus is written

- **WHEN** any deterministic source (seeded, playlist, or womb) produces frames or
  audio
- **THEN** no raw frame or raw PCM is persisted to disk, and only the seed/schedule
  (seeded, womb) or the manifest (playlist) describe the stream

### Requirement: The perceptual stimulus is recorded as a research covariate

The system SHALL record the active feed's reproducible descriptor — covering both
surfaces — in the research submission manifest: for the seeded mode the seed plus
the video and audio schedule parameters, for the playlist mode the single
manifest checksum and per-item digests, **and for the womb mode the seed plus the
womb parameters (heartbeat rate and drift, low-pass corner, luminance mean/contrast/
pulse depth, maternal-state parameters, colour and sense-onset schedule
parameters)**. The descriptor SHALL be sufficient to regenerate (seeded, womb) or
verify (playlist) the entity's full audio-visual perceptual input for the run.

#### Scenario: Seeded descriptor is recorded

- **WHEN** a run uses the seeded source
- **THEN** the submission manifest records the seed and both the video and audio
  schedule parameters

#### Scenario: Playlist descriptor is recorded

- **WHEN** a run uses the playlist source
- **THEN** the submission manifest records the one manifest checksum and item
  digests that pin both surfaces

#### Scenario: Womb descriptor is recorded

- **WHEN** a run uses the womb source
- **THEN** the submission manifest records the seed and the womb parameters
  sufficient to regenerate the full audio-visual stream
