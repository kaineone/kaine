# Audition feed-variant readiness for bake-off task 6.6 (2026-11-16)

Scope: `scripts/bench_audition_encoders.py` versus the three feeds named by OpenSpec task 6.6 (seeded, playlist, stimulus source).

## Does the current script handle real feeds?

No. The current harness evaluates a single synthetic, in-script audio stream only.

- `generate_audio()` builds pink-ish noise plus an injected 1 kHz chirp every `--surprise-interval` blocks. It never imports `kaine.modules.audition.feed`, `kaine.boot.perception_feed`, or any perception-feed config. It does not use `SeededProceduralAudioStream`, `PlaylistAudioStream`, or `StimulusSourceProceduralAudioStream`.
- The synthetic stream is only seeded-audio-like: the sparse surprise bursts mimic the *intent* of seeded surprises, but the PCM, cadence draw, base texture, block timing, and event marks are not taken from the actual seeded feed. Playlist media mixtures and stimulus-source (in-utero) acoustics are not exercised at all.
- Result at commit `871ffe0a`: only one feed family has evidence. The decision note under `docs/records/audition-encoder-decision-note-2026-11-16.md` already records this as the reason 6.6 is not complete.

Conclusion: the script is feed-agnostic today only in the negative sense. It has an internal synthetic generator, but no feed can be selected or replayed.

## What additional loader is needed

A feed replay loader with this contract:

`load_feed(kind, config, n_blocks) -> (blocks: list[bytes], labels: list[int], meta: dict)`

where `len(blocks) == len(labels) == n_blocks` and `blocks[i]` is the PCM bytes the audition encoder would consume (`embed(blocks[i], sample_rate)`).

Required capabilities:

1. Seeded loader
   - Build `SeededAudioSchedule` from `[perception_feed]` / `[perception_feed.audio]` knobs (seed, sample_rate, channels, frames_per_block, base_strength, surprise_strength, surprise_interval shared with video).
   - Construct `SeededProceduralAudioStream(schedule, callback=noop)`.
   - Render deterministically with `stream.pcm_at(i)` so the harness never depends on producer-thread timing.
   - Labels: `stream.surprise_indices(n_blocks)` returned as a 0/1 vector.

2. Playlist loader
   - Load and `verify()` the operator manifest (`load_playlist_manifest`).
   - Emit PCM through `PlaylistAudioStream` (PyAV required; fail honestly if absent).
   - Requires a synchronous capture boundary, because the stream paces output against the shared clock. The loader should capture blocks into a queue until `n_blocks` have arrived or expose direct PCM rendering if added upstream. The scheduler must not run forever during the benchmark.
   - Labels: block indices at item boundaries (position crosses from one manifest item to the next), derived from item durations and the shared clock rather than from decoded content.

3. Stimulus-source loader
   - Build `StimulusSourceAudioSchedule`, `StimulusSourceParams`, the stimulus source clock, and optionally the maternal voice layer and hearing band.
   - Render with `stream.pcm_at(block_index, maturation_progress=..., awake_seconds=...)`.
   - Must fix the womb-state condition for the benchmark (recommended: progress fixed at one declared value, e.g. 0.0 for full in-utero, documented in metadata; not a live changing clock, so results are reproducible).
   - Labels: currently unspecified. A lead decision is needed for what counts as an "event" here (heartbeat thud onsets, maternal-state transitions, or cross-modal transitions). The default recommendation is heartbeat-thud onsets, because they are the feed's only sparse, precomputable markers.

4. Common plumbing
   - Normalize feed output to the harness's 8000-sample/500 ms block contract (`BLOCK_SAMPLES`) or make the harness take a configurable block size from the feed metadata. The feed contracts use `frames_per_block` (commonly 480), so the loader must either pad/concatenate to 8000 samples or parameterize the harness block length. This is an open design choice: keeping each feed's native block size is more faithful, but then the four metrics and latency numbers are measured on different hop lengths and are not directly comparable across feeds.
   - Carry feed metadata (seed, manifest digest, config knobs, label rule) into the output JSON so the record remains auditable.
   - Respect zero-persistence: loaders may open audio for reading and hashing, but must not write PCM or decoded samples to disk.

## Concrete implementation plan for 6.6 completion (checkboxes unchanged)

1. Refactor the synthetic generator into the feed interface.
   - Rename/keep `generate_audio()` as the `synthetic` loader behind the shared `load_feed()` contract. Existing output must remain reproducible bit-for-bit for the current record.

2. Add three real feed loaders (seeded, playlist, stimulus source) using the classes and config already present. No new perception behavior. Handle missing optional dependencies (PyAV, model weights) by skipping that encoder or feed with a reported reason, never fabricating data.

3. Extend CLI.
   - Add `--feed {synthetic,seeded,playlist,stimulus}` (default `synthetic` for backward compatibility).
   - Add feed selectors: `--seed`, `--playlist-manifest`, `--media-root`, `--maturation-progress`, plus overrides for config file and channels.
   - Keep `--blocks`, `--device`, `--surprise-interval`.

4. Parameterize hop length or normalize to 8000 samples.
   - Decide and document whether metrics run on the feed's native `frames_per_block` or a normalized 8000-sample window. Recommend keeping native lengths but storing them in metadata and grouping results by block length in the record.

5. Define and record event marks.
   - Seeded: `surprise_indices`.
   - Playlist: item-boundary indices.
   - Stimulus source: decide with the lead (recommended heartbeat onsets) before implementation; record the rule used.

6. Run each feed and write separate records.
   - Either produce `audition-encoder-bakeoff-{feed}.json` or add a `feed` dimension to the existing JSON. Recommend per-feed files to keep each run reproducible and to avoid conflating evidence from different event types.
   - Preserve the current result file as the synthetic baseline.

7. GPU discipline.
   - The two SSL encoders require the host GPU lock and adequate peak RSS budget (already observed: wavjepa about 3.1 GB, dasheng about 1.7 GB). Run each feed independently so a failure on one feed does not discard the others.

8. Validation.
   - Add smoke tests for the seeded loader (deterministic blocks, labels vector shape, surprise_indices agreement) without requiring real model weights.
   - Verify zero-persistence invariant still holds for the new loader paths.
   - Do not tick task 6.6 until all three feed families have records and the lead confirms the event-mark rules.

## What remains outside this document

- Salience recalibration (6.7), winner promotion to `first_configuration` (6.8), WavJEPA MMN mode (6.9), and the paper revision (6.10) are untouched.
- No task checkboxes were changed by this note.
