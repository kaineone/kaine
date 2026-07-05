# Unified, seed-keyed audio-visual perception feed

## Why

The reproducible perception feed (`reproducible-perception`) today supplies
**vision only**, and the seed only perturbs surprise events — the base visual
world is byte-identical across all seeds (~1.3% of frames differ between two
seeds). A research run that presents *only* a deterministic picture, with no
matching sound and no seed-varied base world, tests a thinner hypothesis than the
composite mind warrants:

- The entity has ears (Audition) but a research run gives them nothing
  reproducible to hear; the only audio path is a live microphone, which is
  neither copyright-free nor replayable.
- Because the base visual world ignores the seed, running several seeds to rule
  out stimulus-specific artifacts does not actually vary the world the world-model
  learns — only which rare blobs appear.
- Picture and sound are wired through two unrelated config sections, so an
  operator's media playlist cannot drive both senses from one source of truth.

## What changes

1. **Seed the base visual world.** The seeded source's base signal becomes a pure
   function of `(seed, frame_index)`, not just `frame_index`. Different seeds yield
   genuinely different — but still bit-identical-per-seed — visual worlds.

2. **Add a deterministic AUDIO feed.** Two new `_AudioStream` sources behind
   Audition's existing `stream_factory` seam:
   - `SeededProceduralAudioStream` — a seeded procedural soundscape (learnable base
     texture + seed-keyed surprise sounds), pure function of `(seed, frame_index)`,
     emitting int16 PCM. No external media, no decode dependency.
   - `PlaylistAudioStream` — decodes the audio track of the **same** checksummed
     manifest media, fail-closed on digest mismatch.

3. **Unify the two surfaces.** Promote the feed to a shared top-level
   `[perception_feed]` section that drives **both** Topos (video) and Audition
   (audio). In `playlist` mode both surfaces walk the same ordered, sha256-pinned
   manifest, so picture and sound come from the same media (a YouTube-style
   playlist carries both). In `seeded` mode one seed drives both procedural
   streams over a shared frame clock, and **surprise events are cross-modal** (a
   surprise fires both a visual blob and an audio burst) so the entity can learn
   audio-visual binding rather than two unrelated streams.

4. **Record both surfaces as one covariate.** The research-submission descriptor
   records the unified feed: seed + video schedule + audio schedule (seeded), or
   the shared manifest checksum + per-item digests (playlist) — sufficient to
   regenerate (seeded) or verify (playlist) the entity's full perceptual input.

The feed continues to ship `mode = "off"` (first boot unchanged, all-off guard
intact), persists no raw frames or PCM (zero-persistence invariant extends to the
audio sources), and never requires live human input for a research run.

## Impact

- **Affected capability:** `reproducible-perception` (vision base-world seeding,
  shared config, unified covariate) plus new audio + unified-A/V requirements.
- **Code:** `kaine/modules/topos/feed.py` (seed the base), new audio sources in
  `kaine/modules/audition/feed.py`, `Audition` gains a `stream_factory` param
  (mirror of `Topos.source_factory`), `kaine/boot.py` builds both factories from
  one `[perception_feed]` section and extends `gather_perception_feed_descriptor`,
  `config/kaine.toml` migrates `[topos.perception_feed]` → `[perception_feed]`,
  `kaine/nexus/health.py` surfaces both surfaces.
- **Dependencies:** playlist-audio decode needs PyAV (`av`) or an ffmpeg fallback
  (cv2 decodes video only); gated behind the `audio`/`vision` extras and
  fail-honest when absent (mirror the existing `PerceptionUnavailableError`).
- **Ships disabled:** `mode = "off"`; no entity boot; respects the all-off
  first-boot guard.
