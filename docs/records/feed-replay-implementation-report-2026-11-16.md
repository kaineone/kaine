# Feed replay implementation report — 2026-11-16

Task 6.6 subset: deterministic audition feed replay loader. Status: in-memory
seeded/repeated-tone/pseudo-noise families implemented and tested; perception-feed
families remain design-only per `audition-feed-integration-note-2026-11-16.md`.

## Files implemented

- `kaine/modules/audition/feed_replay.py` — `load_feed_replay(feed_family, *, seed, n_blocks=12)`; aliases three families (`seeded`/`seeded_synthetic`/`synthetic`, `repeated_tone`/`tone`/..., `pseudo_noise`/`noise`/...); immutable `(blocks, labels, metadata)` tuple contract; `__all__ = ["load_feed_replay"]`.
- `tests/test_audition_feed_replay.py` — 6 tests covering tuple/length invariants, determinism, repeated-tone identity, pseudo-noise distinct blocks, unknown-family `ValueError`, surprise labels.
- `scripts/bench_audition_feeds.py` — bench integration through `build_feed_replay`/`load_feed_replay` aliases (wrapper signatures normalized for family/config/n_blocks/seed).
- `docs/records/audition-feed-integration-note-2026-11-16.md` — design-only note for proposed `*_feed` perception families and required invariants.

No runtime module imports `feed_replay`; it stays a research/replay surface.

## Test results

Command: `.venv/bin/pytest tests/test_audition_feed_replay.py -q`

Result: 6 passed, 1 warning (real KAINE data-root guard disabled due to running
`kaine.cycle` process). No failures.

Verified behaviours: blocks and labels equal length (12 default, 5/6/20 tested);
`bytes`/`bytearray` blocks; deterministic equality across repeated calls with same
seed; repeated tone all blocks identical with `label_rule == "none"`; pseudo-noise
distinct and deterministic blocks; unknown family raises `ValueError`; surprise
labels present for seeded family.

## Missing ruff status

System `PATH` has no `ruff` executable. The project-local binary is
`.venv/bin/ruff`.

Command: `.venv/bin/ruff check kaine/modules/audition/feed_replay.py
tests/test_audition_feed_replay.py`

Result: all checks passed (0 violations). Future gate runs must invoke the
venv-local binary or the pre-flight gate wrapper; a bare `ruff` invocation is
not available on this host.

## Integration notes

- `load_feed_replay` owns in-memory families only. `SeededAudioSchedule` and
  `SeededProceduralAudioStream` are used for `seeded_synthetic`; no audio is
  downloaded, decoded from disk, written to disk, or produced by a producer
  thread. Feed streams are constructed with `callback=lambda _b: None`.
- Metadata carries seed, block geometry (`sample_rate`, `frames_per_block`,
  `block_size`/`block_bytes`, `channels`), counts (several aliases) and
  `label_rule`; seeded metadata also includes `surprise_indices`.
- Canonicalisation keeps backward-compat aliases (`seeded`, `synthetic`,
  `tone`, `noise`, etc.) behind the existing meanings. Real perception feeds,
  if implemented, must use distinct `*_feed` names to avoid colliding with the
  synthetic `seeded` alias (shipped test `load_feed_replay("seeded", seed=42)`
  must remain synthetic).
- Bench script wraps the loader and preserves list conversion for reporting;
  encoder harness compares salience against surprise/label indices.
- Feed replay must remain synchronous and seek-safe via `pcm_at(...)`; producers
  must not be relied on for timing.

## Next gates

1. Perception families (`seeded_feed`, `playlist_feed`, `stimulus_feed`) remain
   pending; implementation must follow the integration note and keep runtime
   behaviour and config defaults unchanged.
2. Add `tests/test_audition_feed_replay_families.py` (or extend existing test)
   per the integration note; gate every family on dependencies (PyAV) honestly
   and fail loudly rather than fabricating PCM.
3. Confirm PyAV/manifest, config knobs, clocks, and fixed womb-state defaults
   before any playlist/stimulus capture runs; record clock origin and label rule.
4. Keep `maternal_distress_excursions` disabled; assert via config guard where
   applicable.
5. Run py_compile + targeted pytest + ruff (venv-local) before each PR; verify
   zero-persistence invariant (no files under configured data root, no thread
   leak, no producer thread start).
6. Lead-confirmed label rule for stimulus family before marking task 6.6 complete
   (`complete_for_feed = false` otherwise).
7. Regenerate synthetic feed benchmark record only if loader defaults/aliases
   change; otherwise no current ruff or test failures to clear.
