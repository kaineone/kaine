## Why

The shakedown entity booted into a **sensory void**: `[topos].capture_enabled =
false`, no media source, and — by the research rule that live human input is not
reproducible — no human in the loop. With nothing to perceive, the forward models
and Phantasia had nothing to predict, prediction error (hence Soma fatigue and the
whole perception→prediction→learning loop) was ill-defined, Lingua had no
experience to condition on, and individuation could not occur because there was
nothing to individuate **from**. The operator's instinct was exactly right: *"I'd
be shocked if we got anything from a sensory void."* (This is the same insight that
motivates `individuation-instrument-gate` — no lived experience, no individuation.)

Research needs **deterministic, reproducible, copyright-free** perceptual
experience: every run must present a bit-identical stimulus stream so results
replicate, and the stream must carry no licensing encumbrance. Live camera and live
human input fail both tests (non-reproducible). The existing live-camera path
(`kaine/modules/topos/live.py`) already exposes the right seam: a `_VideoSource`
Protocol (`open()` / `read()` / `release()`) injected via a `source_factory`, with
the zero-persistence invariant enforced (raw frames live only in process memory).
Nothing yet provides a reproducible source behind that seam.

The operator framed two ways to supply that stimulus:

1. **Operator-curated copyright-free media playlists** — identically repeatable,
   but only if the exact files, order, and timing are pinned; the operator will do
   the media-sourcing research.
2. **A seeded procedural visualizer / noise generator** — generates interesting
   stimulus from a fixed seed, designed to be predicted or surprising at set
   intervals, but **not predictable to a KAINE entity**.

These are not exclusive: both are `_VideoSource` implementations behind one config.
This change builds the **seeded procedural generator as the in-repo default** (so
research is not blocked waiting on media curation) and the **playlist source as a
clean operator-fillable seam** (pinned by a checksummed manifest for
reproducibility). The seeded generator is the recommended canonical stimulus: it is
self-contained, copyright-free by construction, bit-identical per seed, and
purpose-built to drive the prediction loop.

This is **design-of-record** for the rebuild. It boots no entity and ships the feed
**off** (the live-camera default is unchanged); a real research boot selects a
deterministic mode in operator config.

## What Changes

- **Deterministic stimulus sources behind the existing `_VideoSource` seam.** Two
  source types plug into `LiveCamera`'s `source_factory`:
  - `SeededProceduralSource(seed, schedule)` — the in-repo default. Generates each
    frame as a pure function of `(seed, frame_index)`: a structured base signal the
    world model can **learn to predict** (prediction error falls as it learns —
    genuine learning), punctuated by **surprise events at set intervals** whose
    timing/content is drawn from a counter-based PRNG keyed on the seed. The stream
    is therefore **bit-identical across runs of the same seed** (reproducible for
    the experimenter) yet **not predictable to the entity**, which would have to
    invert the keyed PRNG from the pixels to anticipate the next surprise.
  - `PlaylistSource(manifest)` — an operator-supplied list of copyright-free media,
    pinned by a **checksummed manifest** (file digests + order + per-item frame
    timing) so a run is reproducible iff the manifest verifies. The operator sources
    the media; the manifest makes it scientific.
- **Config selects the mode.** A `[topos.perception_feed]` section with
  `mode = "off" | "seeded" | "playlist" | "camera"`, plus `seed`, `surprise_*`
  schedule knobs, and `playlist_manifest`. Shipped `mode = "off"` (guard-consistent).
- **Zero-persistence invariant preserved.** The seeded source generates frames in
  process memory exactly like the camera path; no raw frame is ever persisted (the
  existing AST guard continues to hold). The generator stores only its seed +
  schedule, never rendered frames.
- **Stimulus recorded as a research covariate.** The feed mode and its reproducible
  descriptor (seed + schedule for seeded; manifest checksum for playlist) SHALL be
  recorded in the research submission manifest, so the perceptual input is part of
  the reproducible experimental record (mirrors the abliterated-organ covariate).

## Impact

- Specs: ADD a `reproducible-perception` capability (deterministic sources +
  not-entity-predictable surprise + covariate); the existing `topos` spec is
  unaffected (the live-camera default and disabled-by-default flag stand).
- Code (build phase): `SeededProceduralSource` + `PlaylistSource` implementing
  `_VideoSource`; `LiveCameraConfig`/`source_factory` selection from
  `[topos.perception_feed]`; manifest verify+hash for the playlist; covariate write
  in `kaine/evaluation/submission.py`.
- Config + docs: `[topos.perception_feed]` shipped `off`; present-tense doc of the
  two modes and how to pin a reproducible run. The all-off first-boot guard is
  unaffected (no module flag flips; the feed is a Topos sub-option, shipped off).
- Operator-supplied: the copyright-free media (the operator's stated task). The
  seeded generator needs no external assets and is usable immediately.
- Non-goals: audio-in deterministic stimulus (Audition; a parallel follow-up if
  wanted), embodiment/Mundus, and the entity-initiated locus switch (deferred with
  the reference connector).
