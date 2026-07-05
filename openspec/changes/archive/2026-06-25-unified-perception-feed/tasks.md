# Tasks — unified, seed-keyed A/V perception feed

## 1. Seed the base visual world
- [x] 1.1 In `kaine/modules/topos/feed.py`, derive per-seed base phase/frequency
      offsets from a new `_SALT_BASE` keyed draw; make `frame_at`'s base signal a
      pure function of `(seed, frame_index)` while staying smooth/low-frequency.
- [x] 1.2 Keep invariants: bit-identical per seed, seek-safe, `surprise_strength=0`
      → surprise-free. Update/extend the seeded-source tests to assert a high
      fraction of frames differ between two seeds (regression for the 1.3% bug).

## 2. Deterministic audio sources (`kaine/modules/audition/feed.py`)
- [x] 2.1 Factor the counter-based blake2b PRNG helpers into a shared location
      reusable by both video and audio sources (no logic duplication).
- [x] 2.2 `SeededProceduralAudioStream(_AudioStream)`: `pcm_at(i)` pure function of
      `(seed, frame_index)`; learnable base soundscape + seed-keyed surprise bursts
      on the shared cadence; producer emits `frames_per_block` int16 PCM via the
      `callback`; `start()/stop()/close()`.
- [x] 2.3 `PlaylistAudioStream(_AudioStream)`: reuse `load_playlist_manifest` +
      shared sha256 `verify()` (fail-closed); decode audio via PyAV (`av`),
      resample to `sample_rate`/`channels`, emit PCM; raise
      `PerceptionUnavailableError` with an install hint when `av` is absent.
- [x] 2.4 Zero-persistence: no file writes; PCM only in memory. Extend the
      build-time guard to cover this module.

## 3. Audition plumbing
- [x] 3.1 Add `stream_factory: Callable[..., _AudioStream] | None` to
      `Audition.__init__`; thread it through `_build_default_live_mic` →
      `LiveMicrophone(stream_factory=...)` (mirror of `Topos.source_factory`).

## 4. Shared config + boot wiring
- [x] 4.1 Migrate `config/kaine.toml` `[topos.perception_feed]` → top-level
      `[perception_feed]` with `mode/seed/playlist_manifest` and
      `[perception_feed.video]` / `[perception_feed.audio]` sub-tables; ship
      `mode = "off"`.
- [x] 4.2 In `kaine/boot.py`, read `[perception_feed]` once; build the Topos
      `source_factory` and the Audition `stream_factory` from it; set
      `capture_enabled=True` on both for `seeded`/`playlist`. Map `mode = "live"`
      to the real camera+mic paths. Remove the old `[topos.perception_feed]` read.
- [x] 4.3 Extend `gather_perception_feed_descriptor` to the unified covariate
      (seed + video + audio schedules; or shared manifest digests). Keep it at the
      boot layer and best-effort (never crashes boot).

## 5. Nexus + docs
- [x] 5.1 Update `kaine/nexus/health.py` `_perception_feed_block` to read
      `[perception_feed]` and surface both surfaces (mode, seed, audio + video).
- [x] 5.2 Update docs to present-tense the unified feed and the honest
      synchronization guarantee; refresh any `[topos.perception_feed]` references.

## 6. Verify
- [x] 6.1 `openspec validate unified-perception-feed --strict`.
- [x] 6.2 Full suite green (`.venv/bin/pytest -q -p no:cacheprovider`),
      `lint-imports` green, zero-persistence guard green.
- [x] 6.3 Render a short A/V sample from one seed (visual frames + audio) and
      confirm determinism, to demonstrate the feed end-to-end.
