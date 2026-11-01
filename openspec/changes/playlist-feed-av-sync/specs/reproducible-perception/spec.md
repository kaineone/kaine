## MODIFIED Requirements

### Requirement: The playlist source verifies media and presents it in real time

The playlist source SHALL read one operator-supplied manifest listing each media
item's path, sha256 digest, nominal frame rate, and order, and SHALL verify every
digest before a run. The same manifest SHALL drive both the video and the audio
surface, so picture and sound come from the same media. A digest mismatch SHALL
fail the source for both surfaces (a changed file voids reproducibility). The
nominal frame rate is recorded provenance; the feed SHALL NOT use it to time
presentation.

The playlist feed is a **live / statistical-tier** source: it SHALL present each
item's video and audio at **real wall-clock time (1x)**, dropping or holding
frames to track wall-clock time rather than one frame per cognitive tick. It is
reproducible by **media identity (per-item sha256)**, NOT frame-for-frame: the
exact frame selected at a given tick depends on wall-clock timing, so it
deliberately trades bit-identical frame reproduction for real-time A/V fidelity.
The seeded procedural source remains the bit-identical offline tier.

#### Scenario: A verified manifest is reproducible by media identity

- **WHEN** every item's sha256 matches the manifest
- **THEN** the source opens and both runs present the same media (verified by
  per-item sha256), each paced to real wall-clock time

#### Scenario: A changed file fails closed

- **WHEN** any item's sha256 does not match the manifest
- **THEN** neither the video nor the audio source opens and the run does not
  proceed on unverified media, before a single frame is decoded

## ADDED Requirements

### Requirement: Playlist video is presented by its decoded timestamps

The playlist video source SHALL present, at each read, the latest decoded frame
whose presentation time (`pts × time_base`, relative to the container start) is
at or before the shared clock's offset into the item, and SHALL NOT derive a
frame's time from its index and a frame rate. A frame without a timestamp SHALL
take the previous frame's time plus the stream's frame interval, and a timestamp
at or before the previous frame's time SHALL be held at that time.

#### Scenario: A variable-frame-rate item stays on the sound's time

- **WHEN** an item's frames are spaced unevenly and the manifest gives a nominal
  rate that differs from the average
- **THEN** at every clock offset the presented frame's presentation time is within
  one frame interval before the offset, up to the item's last frame

#### Scenario: Duplicate and missing timestamps

- **WHEN** two frames carry the same timestamp, or a frame carries none
- **THEN** presentation time never runs backwards: the later of the duplicates is
  shown, and the untimed frame is placed one frame interval after the previous one

### Requirement: A playlist video source opened partway into an item seeks

A playlist video source that opens, or falls more than 2 s behind the clock,
partway into an item SHALL seek to the keyframe at or before the clock's offset
and decode forward from it, instead of decoding from the item's first frame.

#### Scenario: A re-opened source resumes at the clock's position

- **WHEN** a playlist video source is opened while the shared clock is well into
  an item
- **THEN** its first read presents a frame within one frame interval of the
  clock's offset, reached by a seek

### Requirement: Both surfaces take an item's length from the container

Both playlist surfaces SHALL register an item's length on the shared clock from
the container duration, not from a frame count and a frame rate. When the
container reports no duration, the video SHALL register the end of its last
frame when it reaches the end of the stream.

#### Scenario: The item length comes from the container

- **WHEN** either surface opens an item first
- **THEN** the shared clock's length for that item is the container duration

### Requirement: Playlist audio carries exactly the decoded samples

The playlist audio source SHALL deliver, for each resampled frame, exactly the
frame's samples (`frame.samples` per channel, interleaved for planar layouts) and
never a plane's padded buffer, and SHALL flush the resampler at the end of each
item.

#### Scenario: An item's audio is as long as the item

- **WHEN** an item is decoded from start to end
- **THEN** the audio delivered for it lasts the item's container duration, within
  one block

### Requirement: Playlist audio stays on the item's timeline

The playlist audio source SHALL place decoded audio on the item's timeline by the
decoded frames' timestamps: a gap longer than 40 ms SHALL be filled with silence
and audio more than 40 ms before the current position SHALL be trimmed. At the
end of an item the audio SHALL be padded with silence, or trimmed, to the item's
length on the shared clock, and an item with no audio track SHALL be heard as
silence for its length.

#### Scenario: Picture and sound meet at a marked moment

- **WHEN** an item carries a visual and an audible marker at the same media time
- **THEN** the audio delivered at that moment of the clock and the frame presented
  at it both carry the marker

#### Scenario: A gap in the audio timestamps

- **WHEN** an item's audio timestamps jump forward by more than 40 ms
- **THEN** the gap is heard as silence and the audio after it stays on the item's
  timeline

#### Scenario: An item without an audio track

- **WHEN** an item has no audio track
- **THEN** silence is delivered for the item's length and the next item's sound
  starts when the clock reaches it

### Requirement: Playlist audio is paced against the shared clock

The playlist audio source SHALL emit each block when the shared clock reaches the
block's place on the item timeline, and SHALL NOT keep a lag after a late block.
A block owed up to 0.5 s SHALL be emitted at once, so the owed blocks catch the
delivered position up to the clock; a block owed more than 0.5 s SHALL make the
source resume at the clock's item and offset and log the skip without content.
Time during which the clock is paused SHALL NOT count as owed.

#### Scenario: A short stall is caught up

- **WHEN** the audio producer is held up for 0.3 s
- **THEN** the owed blocks are emitted back to back, no audio is skipped, and the
  delivered position is back on the clock within the next 0.3 s of blocks

#### Scenario: A long stall skips forward

- **WHEN** the audio producer is held up for 2 s
- **THEN** it resumes at the clock's position, logs the skip once with no title,
  path or audio, and the sound delivered at each later moment of the clock is the
  sound of that moment

#### Scenario: A pause is not a debt

- **WHEN** the shared clock is paused for 5 s while the producer is waiting
- **THEN** no block is caught up or skipped when it resumes
