# Audition sensor-feed checklist — 2026-11-16

Report only. No task checkboxes were changed, no config was changed, no
perception/run artifacts were created or modified.

## Task status

- OpenSpec task 6.6 (`scripts/bench_audition_encoders.py` bake-off on the
  seeded, playlist, and stimulus source feeds, with the four design metrics) is
  **incomplete**. Task 6.6 must remain unchecked. It may only be ticked when all
  three feed families have recorded results and the lead confirms the event-mark
  rules.

Current evidence position:

- Synthetic (pink-ish noise with a 1 kHz surprise chirp) only: one record exists
  at `docs/records/audition-encoder-bakeoff.json`, summarised in
  `docs/records/audition-encoder-decision-note-2026-11-16.md`.
- Seeded, playlist, and stimulus source feeds: **not yet replayed** through the
  harness.

## Pending gates (none ticked)

- [ ] 6.6 completion: seeded feed replayed and recorded.
- [ ] 6.6 completion: playlist feed replayed and recorded.
- [ ] 6.6 completion: stimulus source feed replayed and recorded.
- [ ] 6.6 completion: lead confirms event-mark rules for all three feeds.
- [ ] 6.6 completion: all three feed families have per-feed records; task ticked
      only then.
- [ ] Zero-persistence invariant verified for new loader paths (no PCM or decoded
      samples written to disk; opening for reading/hash only).
- [ ] Host GPU lock held and peak RSS budget verified for `wavjepa` (~3.1 GB)
      and `dasheng` (~1.7 GB); each feed run independent.
- [ ] Feed metadata (seed, manifest digest, config knobs, label rule) carried
      into output JSON for auditability.
- [ ] Synthetic baseline preserved as the existing result file.

## Evidence schema (required for every feed run)

Common envelope for each encoder/feed result record:

```json
{
  "record_id": "<run/feed identifier>",
  "feed": "synthetic | seeded | playlist | stimulus",
  "created_at_utc": "<ISO-8601>",
  "task": "6.6",
  "complete_for_feed": false,
  "config": {
    "blocks": 600,
    "block_samples": 8000,
    "sample_rate_hz": 16000,
    "device": "cuda:0",
    "surprise_interval_blocks": 150,
    "seed": 42
  },
  "encoder": "spectral | dasheng | wavjepa",
  "metrics": {
    "roc_auc": 0.0,
    "false_alerts_per_min": 0.0,
    "p95_latency_ms": 0.0,
    "peak_rss_mb": 0,
    "embed_dim": 0
  },
  "labels": {
    "count": 600,
    "ones": 0,
    "rule": "<feed-specific label rule>"
  },
  "block_samples_actual": 8000,
  "zero_persistence_attested": true,
  "host_gpu_lock": "<lock identifier or null>",
  "notes": ""
}
```

### Seeded feed

- loader: `load_feed("seeded", ...)` building `SeededAudioSchedule` from
  `[perception_feed]` / `[perception_feed.audio]` knobs (seed, sample_rate,
  channels, frames_per_block, base_strength, surprise_strength,
  surprise_interval shared with video); construct
  `SeededProceduralAudioStream(schedule, callback=noop)`; render deterministically
  with `stream.pcm_at(i)`.
- required feed fields:
  - `seed`
  - `sample_rate`
  - `channels`
  - `frames_per_block`
  - `base_strength`
  - `surprise_strength`
  - `surprise_interval`
- `label_rule`: `"surprise_indices"`; labels are `stream.surprise_indices(n_blocks)`
  as a 0/1 vector with `len(labels) == n_blocks`.
- expected evidence fields: `surprise_indices_count`, `schedule_knobs`, and the
  common metrics/envelope.

### Playlist feed

- loader: `load_playlist_manifest` + `verify()`; emit PCM through
  `PlaylistAudioStream` (PyAV required; honest skip if absent); capture blocks
  through a synchronous capture boundary until `n_blocks` arrive or use direct PCM
  rendering if added upstream; scheduler must not run forever.
- required feed fields:
  - `playlist_manifest`
  - `manifest_digest`
  - `media_root`
  - `pyav_available`
- `label_rule`: `"item_boundary_indices"`; block indices where position crosses
  from one manifest item to the next, derived from item durations and the shared
  clock rather than decoded content.
- expected evidence fields: `item_count`, `item_boundary_indices`, `decoder`,
  and the common metrics/envelope.

### Stimulus source feed

- loader: build `StimulusSourceAudioSchedule`, `StimulusSourceParams`, stimulus
  source clock, and optionally maternal voice layer and hearing band; render with
  `stream.pcm_at(block_index, maturation_progress=..., awake_seconds=...)`.
- required feed fields:
  - `maturation_progress` (fixed at one declared value, e.g. 0.0 for full
    in-utero; documented in metadata; not a live changing clock)
  - `awake_seconds` (as declared for reproducibility)
  - `stimulus_source_clock`
  - `maternal_voice_layer` (optional; present/absent stated)
  - `hearing_band` (optional; present/absent stated)
- `label_rule`: lead decision pending; recommended `"heartbeat_thud_onsets"`.
  The rule actually used must be recorded in the result before 6.6 can close.
- expected evidence fields: `womb_state`, `label_rule`, and the common
  metrics/envelope.

## Design note on block size

Feed contracts use `frames_per_block` (commonly 480) while the current harness
uses an 8000-sample (500 ms) block. Each evidence record must state
`block_samples_actual` and whether results are grouped by that block length
(recommended) or normalised to 8000 samples. Cross-feed comparison is only
valid within the same block length.

## Relationship to other tasks

- 6.7 (salience recalibration), 6.8 (winner promotion to `first_configuration`),
  6.9 (WavJEPA MMN mode), and 6.10 (paper revision note) remain untouched.
- 0.1 (audio encoder selection) remains unchecked until 6.8 lands.

Changed path: `docs/records/audition-sensor-feed-checklist-2026-11-16.md`.