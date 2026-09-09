## MODIFIED Requirements

### Requirement: The playlist feed presents synchronized audio-visual perception in real time

The reproducible playlist feed SHALL present each manifest item's video and audio at
**real wall-clock time (1×)**, so that at any moment the video frame and the audio
being perceived come from the **same manifest item at the same media position**. The
feed is a **live / statistical-tier** source: reproducible by **per-item sha256**
(media identity), not by frame-for-frame bit-identical reproduction. The seeded
procedural feed remains the bit-identical offline-tier source and is unaffected. The
zero-persistence invariant (raw frames and audio live only in process memory) is
unaffected.

#### Scenario: Video is paced to real time

- **WHEN** the playlist feed is read over a wall-clock interval
- **THEN** the video advances at the item's real frame rate (1×), not at the
  cognitive-tick rate, dropping or holding frames to track wall-clock time

#### Scenario: Audio and video stay on the same item

- **WHEN** playback crosses a manifest item boundary
- **THEN** the video feed and the audio feed advance to the next item together, so
  the entity never sees one item while hearing another

#### Scenario: The playing item is observable on the bus

- **WHEN** a `topos.report` or `audition.perception` event is published while the
  playlist feed is active
- **THEN** the event payload carries the current item's title (basename) and manifest
  order, so the playing media is read off the bus rather than inferred from process
  file descriptors

#### Scenario: Media identity is still verified fail-closed

- **WHEN** a manifest item's file does not match its declared sha256
- **THEN** the feed fails closed before decoding a single frame (unchanged), so
  real-time pacing does not weaken media-identity verification
