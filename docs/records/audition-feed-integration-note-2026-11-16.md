# Audition feed integration note (feed_replay) — 2026-11-16

Scope: design only. No runtime behaviour changes, no source edits, no task checkboxes changed.
Target module: `kaine/modules/audition/feed_replay.py` (`load_feed_replay`).

## Invariants (must hold for any extension)

- `feed_replay` is a research/replay surface. It must never be imported by
  runtime module code, never `start()` a producer thread, and never alter
  `LiveMicrophone` / stream-factory behaviour.
- Rendering is synchronous and seek-safe: prefer each feed's `pcm_at(...)`
  direct render; never rely on producer-thread timing.
- Zero persistence: PCM and decoded samples stay in process memory only. Feed
  objects are constructed with `callback=lambda _b: None`; no file writes.
- Immutable return contract remains
  `(blocks: tuple[bytes, ...], labels: tuple[int, ...], metadata: dict[str, Any])`
  with `len(blocks) == len(labels)`.
- Backward compatibility: existing aliases and identities
  (`seeded` currently -> `seeded_synthetic`, `synthetic`, `repeated_tone`,
  `pseudo_noise`, `surprise_indices`) must keep their current meanings, or be
  moved behind a clearly versioned alias with a recorded deprecation note.

## Proposed loader extension (additive)

Keep `load_feed_replay(feed_family, *, seed, n_blocks=...)` for the three
in-memory families. Add a separate, explicitly-named entry point for
perception-feed-derived families so names do not collide with the synthetic
aliases:

```python
load_feed_replay_family(
    family: str,                   # "seeded_feed" | "playlist_feed" | "stimulus_feed"
    *, seed: int,
    n_blocks: int = DEFAULT_BLOCKS,
    config: Mapping[str, Any] | None = None,
    playlist_manifest: str | Path | None = None,
    media_root: str | Path | None = None,
    maturation_progress: float = 0.0,
    awake_seconds: float = 0.0,
) -> tuple[tuple[bytes, ...], tuple[int, ...], dict[str, Any]]
```

Alias table (back-compat preserved):

| Requested | Resolves to | Notes |
|---|---|---|
| `seeded_synthetic`, `seeded` (legacy) | `seeded_synthetic` | unchanged behaviour |
| `repeated_tone`, `tone`, ... | `repeated_tone` | unchanged |
| `pseudo_noise`, `noise`, ... | `pseudo_noise` | unchanged |
| `seeded_feed` (new) | real seeded feed | `SeededProceduralAudioStream` |
| `playlist_feed` (new) | playlist feed | `PlaylistAudioStream` (PyAV) |
| `stimulus_feed` (new) | stimulus source | `StimulusSourceProceduralAudioStream` |

Rationale: `seeded` already means the synthetic family in
`tests/test_audition_feed_replay.py` (`load_feed_replay("seeded", seed=42)`).
Renaming it would break shipped tests and the synthetic baseline record. Real
feeds get distinct `*_feed` names and the feed-specific richer signature.

## Family: seeded_feed

Construction (no thread, no callback side effects):

- `SeededAudioSchedule(seed=..., sample_rate, channels, frames_per_block,
  surprise_interval, base_strength, surprise_strength)` from config knobs.
- Shared cross-modal contract: `surprise_interval` must equal the video
  schedule's value; default from `[perception_feed.video].surprise_interval`.
- `SeededProceduralAudioStream(schedule, callback=lambda _b: None)`.
- Render `blocks[i] = stream.pcm_at(i)` for `i in range(n_blocks)`.
- Labels: `1 if i in set(stream.surprise_indices(n_blocks)) else 0`.
- Label rule: `"surprise_indices"`.

Knobs sourced from `[perception_feed]` (seed) and `[perception_feed.audio]`
(sample_rate, channels, frames_per_block, base_strength, surprise_strength);
plus `[perception_feed.video].surprise_interval`. Defaults in
`feed_replay` must mirror the config defaults so a no-config call reproduces
the documented baseline.

Metadata must include: seed, sample_rate, channels, frames_per_block,
surprise_interval, base_strength, surprise_strength, block_count, sample_rate,
label_rule, surprise_indices (tuple).

## Family: playlist_feed

Prerequisites: `av` (PyAV) installed and operator manifest available. Fail
honestly (`PerceptionUnavailableError` or `ValueError`) rather than fabricating
synthetic PCM when PyAV or the manifest is absent.

Rendering strategy (synchronous, bounded):

- `load_playlist_manifest(path)` then `manifest.verify()`.
- Shared clock: construct `PlaylistClock(len(manifest.items))` and inject it
  (`playlist_clock=`) so audio and (conceptually) video agree; a private clock is
  acceptable only for a standalone audio replay.
- Construct `PlaylistAudioStream(manifest, callback=noop, sample_rate, channels,
  frames_per_block, media_root=..., playlist_clock=clock)`.
- The producer is paced; the loader must capture exactly `n_blocks` blocks into
  an in-memory `queue`/list and then `stop()`. Implement a bounded capture with
  a wall-clock timeout and fail loudly (not silently truncate) if fewer than
  `n_blocks` arrive.
- The shared clock must be started at a documented origin (`clock.start()` or
  equivalent) before capture so positions are reproducible; record the origin in
  metadata.
- Labels: item-boundary indices. A label is `1` at block `i` when the producer's
  delivered item index changes between block `i-1` and block `i` (including the
  first block of a new item). Derive from delivered positions / manifest item
  durations on the shared clock, not from decoded PCM content. If the producer
  wraps, record wrap count.
- Label rule: `"item_boundary_indices"`.
- Metadata: playlist_manifest path, manifest digest (from `manifest`), item
  count, media_root, pyav version (if importable), sample_rate, channels,
  frames_per_block, block_count, clock origin, item_boundary_indices, wrap count,
  decoder.

## Family: stimulus_feed

Construction:

- `StimulusSourceAudioSchedule(seed, sample_rate, channels, frames_per_block)` from
  `[perception_feed.stimulus_source.audio]` (and base `[perception_feed.audio]`).
- `StimulusSourceParams` from `[perception_feed.stimulus_source]` knobs.
- Stimulus source clock from the perception module (the same clock used at
  runtime); a replay must fix the clock origin and never let it run against wall
  time without a documented seed-derived offset.
- Optional maternal voice layer from `[perception_feed.stimulus_source.voice]`
  (pre-rendered data under `kaine/modules/audition/maternal_voice_data/`); if
  `enabled = false`, render voice-free (byte-identical to the voice-free path).
- Optional hearing band from `[perception_feed.stimulus_source.hearing]`.
- Construct `StimulusSourceProceduralAudioStream(schedule, params=params, clock=clock,
  callback=noop, voice=..., awake=lambda: fixed_awake_seconds, hearing=...,
  hearing_stage=lambda: fixed_stage)`.
- Render `stream.pcm_at(i, maturation_progress=fixed, awake_seconds=fixed)` for a
  single declared womb state. Default `maturation_progress=0.0` (full in-utero)
  and a documented `awake_seconds` (default 0.0). Document both in metadata.
- Hearing stage fixed to 0 unless the design note author specifies otherwise;
  changing it must be recorded in metadata.

Labels: lead decision pending. Recommended default: heartbeat-thud onsets,
because they are the feed's only sparse, precomputable markers. If adopted, the
label rule records `"heartbeat_thud_onsets"` and marks only blocks containing a
thud onset. Until the lead confirms, the loader should expose the chosen rule as
metadata `"label_rule"` and accept an explicit `label_rule` argument (defaulting
to the recommended value) so runs are auditable. Any run whose label rule is not
lead-confirmed must set `complete_for_feed = false` in the evidence record.

Metadata: seed, sample_rate, channels, frames_per_block, maturation_progress,
awake_seconds, hearing stage, maternal voice present/absent, hearing band
present/absent, stimulus source clock origin, label_rule, heartbeat_onset_indices
(when applicable), plus config knobs.

## Block size / comparability (open design choice)

Keep each feed's native `frames_per_block` (commonly 480) rather than
normalising to 8000 samples inside `feed_replay`. Rationale: `pcm_at` is a pure
function of block size; concatenating/padding to 8000 changes event times and
breaks auditability. Cross-feed comparison validity is handled in the evidence
record through `block_samples_actual` and grouping by block length, per the
existing checklist. The loader must never silently resample or pad.

## Tests to add when the loader exists

Add a new test module `tests/test_audition_feed_replay_families.py` (or extend
`tests/test_audition_feed_replay.py`) covering, all without real model weights
and without touching disk:

1. Identity / aliases
   - `load_feed_replay("seeded", ...)` still returns the synthetic family
     (back-compat) and equals `load_feed_replay("seeded_synthetic", ...)`.
   - `load_feed_replay_family("seeded_feed", ...)` returns blocks whose byte
     length is `frames_per_block * channels * 2` for every block.
   - Unknown family raises `ValueError`.

2. Determinism
   - Repeated calls with identical arguments (including `config`, fixed clock
     origin) produce byte-identical tuples for seeded_feed; voice-free path is
     byte-identical; voice-enabled path is byte-identical given identical
     awake_seconds.
   - Stimulus rendering with `maturation_progress=0.0` and `1.0` produces
     different blocks; progress scaling applies to amplitude as documented.

3. Seeded_feed
   - `len(blocks) == len(labels) == n_blocks`.
   - Surprise labels agree with `SeededProceduralAudioStream.surprise_indices`
     when reconstructed from metadata knobs.
   - `sample_rate`, `frames_per_block`, `seed` round-trip through metadata.
   - Surprise at block 0 is false (`_is_surprise_block(0)` is false).
   - Cross-modal cadence: for the same seed, surprise indices match a
     independently reconstructed stream.

4. Playlist_feed (gate on PyAV availability)
   - Skip with a recorded reason when `av` is not importable; do not fabricate
     data.
   - Manifest verify failure surfaces as an error before any PCM is produced.
   - Item-boundary labels length equals `n_blocks`; first block of a new item is
     labeled 1; number of 1s is consistent with manifest item count.
   - Bounded capture: requesting `n_blocks` produces exactly `n_blocks` or
     raises, never hangs; capture stops the producer.
   - Clock origin recorded in metadata and stable across reruns.

5. Stimulus_feed
   - Fixed womb state: default `maturation_progress == 0.0`; changing it
     changes blocks but keeps length.
   - Voice absent vs present metadata flag; voice-enabled bytes differ but path
     is deterministic.
   - Hearing band enabled vs disabled: disabled path byte-identical to the
     no-band path.
   - `maternal_distress_excursions` is never enabled (config guard).
   - Metadata records `label_rule`, including whether lead-confirmed.

6. Zero persistence
   - Run the existing invariant test pattern
     (`tests/test_zero_persistence_invariant.py`) against the new families:
     no files created under the configured data root / temp; PCM never written.
   - Constructor uses `callback=lambda _b: None`; ensure producer thread not
     started by loader (thread count unchanged, or threads joined).

7. Availability / errors
   - Playlist missing PyAV -> `PerceptionUnavailableError` (or documented
     equivalent) with install hint, not a synthetic fallback.
   - Playlist missing/invalid manifest -> error before capture.
   - Seeded config with `channels not in {1,2}` for playlist path -> `ValueError`.
   - `n_blocks <= 0` -> `ValueError`.
   - Stimulus voice sample-rate mismatch -> `ValueError`.

## Non-goals / unchanged

- No changes to runtime behaviour, modules, or config defaults.
- No task checkbox changes; 6.6 remains incomplete until all families have
  records and label rules are lead-confirmed.
- No new perception behaviour; only reuse existing classes and config.
- No `.md` beyond this note.
