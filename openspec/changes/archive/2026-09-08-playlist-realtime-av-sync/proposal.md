## Why

The reproducible playlist feed decodes each manifest item's **video and audio in
two independent decoders** that share no clock and no item cursor:

- **Topos (video)** pulls one frame per cognitive tick through `cv2.VideoCapture`
  (`PlaylistSource`). It is paced by the tick loop, **not** by the file's frame
  rate, so a 24 fps clip is consumed at roughly the tick rate (~10 Hz frame-ticks
  ≈ 0.4× real time).
- **Audition (audio)** decodes the same file's audio track through PyAV
  (`PlaylistAudioStream`) in a producer thread that **paces itself to real wall-clock
  time** (1×) with `sleep`s.

Equal-length tracks consumed at unequal speeds finish at different wall-clock
moments and cross item boundaries independently. The feed docstring's claim of
"clip-level synchronization" is aspirational — nothing enforces it. Observed live
in a base-thesis run over a two-item playlist:

- After ~69 minutes, the **audio had finished item 0 and was ~20% into item 1**,
  while the **video was still ~36% through item 0** — the entity was *seeing* one
  show and *hearing another*. Open file descriptors confirmed both media files
  held at once, with only the audio advancing at a real-time byte rate.
- The audition alert-rate and arousal surge that looked like an in-scene event was
  in fact the **audio crossing into the next episode under the unchanged video**.

Two consequences make the feed unfit for the paper's live perceptual tier as-is:

1. **Cross-modal provenance breaks at every item boundary** and drifts continuously
   within long items, so "synchronized audio-visual perception from a reference
   corpus" cannot be claimed.
2. **The current item is not observable on the bus.** Payloads carry no title;
   audition labels its source `live_mic` regardless of the playing file, so "which
   show is it watching" is answerable only by inspecting process file descriptors.

## Decision

Pace the playlist feed to **real wall-clock time (1×)** for both modalities, the way
a media player presents a file. This is an operator decision (2026-07-12) that
**deliberately trades bit-identical frame reproduction for real-time A/V fidelity**:

- The playlist feed is reclassified as a **live / statistical-tier** source —
  reproducible by **media identity (per-item sha256)**, not frame-for-frame. This
  matches the paper's live-tier reproducibility model (validity by statistical
  replication across runs, not bit-for-bit).
- The **seeded procedural feed** remains the bit-identical **offline** deterministic
  tier and is unchanged.
- This complements, and does not replace, the **VLC window-share + desktop-audio**
  field-tier path (a single already-synchronized real-time presentation captured
  from outside the process).

The frame-locked-deterministic alternative (advance audio by the video frame cursor,
keeping bit-identical reproduction at the cost of non-real-time playback) was
considered and set aside: real-time fidelity was preferred for these runs.

## What Changes

1. **Real-time video pacing.** `PlaylistSource.read()` returns the frame at the
   current elapsed wall-clock position (`elapsed × item.fps`), dropping or holding
   frames to track 1×, instead of returning the next sequential frame. An injectable
   clock keeps this testable. The item advances when the real-time position passes
   the file's end.
2. **Boundary alignment.** Video and audio derive their position from a shared
   playlist start-clock (one monotonic origin + per-item durations) so both feeds
   are on the same item at the same wall-clock time and cross boundaries together;
   residual sub-second skew is acceptable for the live tier.
3. **On-bus provenance.** Both feeds expose the current item, and Topos and Audition
   stamp the item title (basename) + manifest order + media offset/PTS on their
   report payloads, so the playing item is read off the bus rather than inferred
   from file descriptors.
4. **Reclassify reproducibility.** Update the `feed.py` docstring and the
   `reproducible-perception-feed` change notes: the playlist feed is a live /
   statistical-tier source (reproducible by media sha256), no longer asserting
   bit-identical frame reproduction. The zero-persistence invariant is unaffected.
5. **Relax the determinism tests** that assert frame *i* → media frame *i* for the
   playlist, and add tests for: real-time frame selection at a given elapsed,
   item advance at real-time end, boundary co-advance of the two feeds under a
   shared clock, and item provenance present on both payloads.

Out of scope: the seeded procedural feed, the VLC/screen-share field-tier path, and
any change to the audio feed's existing real-time pacing beyond sharing the clock.
