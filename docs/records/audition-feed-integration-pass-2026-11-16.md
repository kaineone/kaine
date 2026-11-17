# Audition feed integration pass — 2026-11-16

Report only. No source modifications, no task checkboxes changed, no runtime or
perception-feed artifacts were created or modified. This pass records the current
state of the deterministic audition feed replay loader against the audition
sensor-feed checklist.

## Inputs reviewed

- `kaine/modules/audition/feed_replay.py` (`load_feed_replay`).
- `tests/test_audition_feed_replay.py`.
- `docs/records/audition-sensor-feed-checklist-2026-11-16.md`.
- `docs/records/audition-feed-integration-note-2026-11-16.md`.

## Loader state observed

Current public API: `load_feed_replay(feed_family, *, seed, n_blocks=DEFAULT_BLOCKS)`.

Constants:
- `SAMPLE_RATE = 16000`
- `FRAMES_PER_BLOCK = 480`
- `CHANNELS = 1`
- `DEFAULT_BLOCKS = 12`
- `BLOCK_BYTES = 960`

Currently implemented feed families (all in-memory, deterministic, seed-keyed,
PCM returned as bytes, no persistence, `callback=lambda _b: None`):

| Requested alias | Canonical family |
|---|---|
| `seeded`, `seeded_synthetic`, `synthetic`, `synthetic_seeded`, `seededsynthetic` | `seeded_synthetic` |
| `repeated`, `repeated_tone`, `tone`, `tone_pattern`, `single_tone`, ... | `repeated_tone` |
| `noise`, `pseudo_noise`, `pseudo-noise`, `pseudonoise`, `deterministic_noise`, `pseudo_noise_feed` | `pseudo_noise` |

Return contract observed: `(tuple[bytes, ...], tuple[int, ...], dict[str, Any])`,
with `len(blocks) == len(labels)`. `unknown_family` raises `ValueError`; `n_blocks <= 0`
raises `ValueError`.

Observed metadata (synthetic family):
- `feed_family` / `family` = `seeded_synthetic`
- `seed`, `block_count` / `n_blocks` / `count`
- `sample_rate`, `frames_per_block`, `block_samples`, `block_size`, `channels`
- `label_rule` = `surprise_indices`
- `surprise_indices` tuple

Observed seeded synthetic behavior with `seed=42, n_blocks=20`: labels contained 2
ones and `surprise_indices = (12, 16)`. These are synthetic seeded-audio surprises,
not perception-feed replay.

Observed error semantics: unknown families and non-positive block counts are rejected
before any data generation.

## Verification run

Command run (read-only verification):

```bash
.venv/bin/python -m pytest -q tests/test_audition_feed_replay.py
```

Result: `6 passed, 1 warning`, warning only from disabled real data-root guard (a
live `kaine.cycle` process). No source changes were made.

Additional representative loader check:

```text
seed=42, n_blocks=6:
  seeded/seded_synthetic: 6 blocks, 6 labels, 960 bytes/block, 0 surprise labels in this window
  repeated_tone: 6 blocks, 6 labels, 960 bytes/block, 0 labels
  pseudo_noise: 6 blocks, 6 labels, 960 bytes/block, 0 labels
constants: SAMPLE_RATE=16000, FRAMES_PER_BLOCK=480, CHANNELS=1, DEFAULT_BLOCKS=12, BLOCK_BYTES=960
```

## Sensor-feed checklist cross-reference

Task 6.6 remains incomplete, consistent with the checklist. The newly implemented
loader is an in-memory synthetic-family replay path only; it does not yet implement
the perception-feed-derived families named by task 6.6.

Checklist gate status after this pass:

- [x] Replay loader exists and is covered by `tests/test_audition_feed_replay.py`.
- [x] `seeded` alias still resolves to the synthetic baseline family; backward
      compatibility is preserved.
- [x] Zero-persistence invariant is built into the loader implementation
      (PCM stays in process memory; `callback=lambda _b: None`).
- [ ] Seeded perception feed replayed through `SeededProceduralAudioStream`.
- [ ] Playlist feed replayed through `PlaylistAudioStream`.
- [ ] Stimulus source feed replayed through `StimulusSourceProceduralAudioStream`.
- [ ] Event-mark rules confirmed by the lead for all three feeds.
- [ ] All three feed families have recorded evidence; task 6.6 can only be ticked
      then.
- [ ] Host GPU lock and peak RSS gates remain pending for `wavjepa` and `dasheng`.
- [ ] Feed metadata from real perception feeds recorded in result JSON (seed,
      manifest digest, config knobs, label rule).

## Gap statement

The checklist requires three feed families: seeded, playlist, and stimulus source.
The current loader provides three in-memory families: `seeded_synthetic`,
`repeated_tone`, and `pseudo_noise`. Real perception-feed replay remains proposed
in `docs/records/audition-feed-integration-note-2026-11-16.md` under distinct
`*_feed` names and has not yet been implemented. Therefore:

- No 6.6 checkboxes may be ticked.
- Synthetic baseline evidence remains valid at
  `docs/records/audition-encoder-bakeoff.json`.
- Task 0.1 remains unchecked until task 6.8 lands.

## Follow-up integration items

1. Add distinct `seeded_feed`, `playlist_feed`, and `stimulus_feed` entry points that
   reuse existing perception classes and config without changing runtime behavior.
2. Preserve the legacy `seeded` alias for the synthetic family, as documented in the
   integration note.
3. Capture exactly `n_blocks` for playlist feeds and verify PyAV presence honestly.
4. Fix the womb state, maternal voice availability, and hearing band metadata for
   stimulus source replay.
5. Produce per-feed result records carrying native `frames_per_block` and
   `block_samples_actual`.
6. Re-run the checklist against the new families before task 6.6 can close.

## Result

Created `docs/records/audition-feed-integration-pass-2026-11-16.md`. No source
files were modified.
