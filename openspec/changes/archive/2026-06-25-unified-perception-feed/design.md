# Design — unified, seed-keyed A/V perception feed

## Shared config: `[perception_feed]`

The feed moves from `[topos.perception_feed]` to a single top-level
`[perception_feed]` that both Topos and Audition read. There are no external
operators yet (pre-publication), nothing has booted, and the feed ships off, so
this is a clean migration, not a dual-support compatibility layer (avoids cruft
per "do it right the first time").

```toml
[perception_feed]
mode = "off"                 # off | seeded | playlist | live
seed = 0                     # seeded: both surfaces are a pure function of this
playlist_manifest = ""       # playlist: path to the shared checksummed manifest

[perception_feed.video]      # seeded-video knobs (geometry from [topos])
surprise_interval = 150
surprise_strength = 1.0

[perception_feed.audio]      # seeded-audio knobs
sample_rate = 16000          # match Audition capture_sample_rate
channels = 1
base_strength = 0.3          # learnable base soundscape amplitude
surprise_strength = 1.0      # seed-keyed surprise-burst amplitude
```

- `mode = "live"` replaces the old video-only `"camera"`: the real camera *and*
  the real microphone (the existing live paths). `off` leaves both capture paths
  disabled (first-boot default).
- The cross-modal **surprise cadence is shared**: `surprise_interval` lives under
  `[perception_feed.video]` and the audio source reuses it, so a surprise slot
  fires both modalities. `surprise_strength` is per-surface (a blob and a burst
  can have independent magnitudes; either may be 0 to silence one modality's
  surprises).

`boot.py` reads `[perception_feed]` once and injects a `source_factory` into Topos
and a `stream_factory` into Audition. `make_topos`/`make_audition` no longer own
the feed section; they receive the built factory + a `capture_enabled=True` when a
deterministic mode is selected (mirrors today's Topos wiring).

## Seeding the base visual world

Today `frame_at` computes `base_r/base_g/base_b` from `frame_index` only. Make the
base a function of `(seed, frame_index)` by deriving a small set of per-seed phase
and frequency offsets from the keyed PRNG (new salt `_SALT_BASE`):

- per-channel spatial phase offsets `φ_r, φ_g, φ_b ∈ [0, 1)` from
  `_keyed_u64(seed, 0, _SALT_BASE | channel)`,
- per-seed drift rates and a wave frequency within bounded ranges, so every seed
  is a *different but equally learnable* smooth low-frequency world.

Invariants preserved: pure function of `(seed, frame_index)` (seek-safe,
bit-identical per seed); base stays smooth/low-frequency (world-model-learnable);
`surprise_strength = 0` still yields a surprise-free stream. The
"different seeds decorrelate" scenario strengthens from "surprise schedules
decorrelate" to "the base worlds differ," and a regression test asserts a high
fraction of frames differ between two seeds (not ~1%).

## Audio sources (`kaine/modules/audition/feed.py`)

Both implement the `_AudioStream` protocol (`start()/stop()/close()`) and push
int16 little-endian PCM into the `callback` the `stream_factory` is handed —
exactly what `_default_stream_factory` (sounddevice) does today. They run a small
producer thread/timer that emits `frames_per_block`-sized blocks at the configured
`sample_rate`, so `LiveMicrophone`'s VAD/segmentation pipeline is unchanged.

### `SeededProceduralAudioStream`
- `pcm_at(frame_index) -> bytes`: pure function of `(seed, frame_index)` via the
  same counter-based blake2b PRNG (shared helper, distinct salts), mirroring the
  video source. Block `i` is identical across runs and independent of read order.
- **Base soundscape:** a sum of a few low-frequency sinusoids whose
  frequencies/phases are seed-derived — a learnable auditory texture, the audio
  analogue of the drifting visual gradients. Amplitude `base_strength`.
- **Surprise bursts:** on the shared surprise slots, a seed-keyed short burst
  (noise/chirp) whose timbre and amplitude come from the content draw.
- Emits silence-free low-level texture so Audition's RMS/VAD sees continuous
  input; segmentation still chunks it into "utterances" of sound for the encoder.
  (Honest note: this is sound, not speech — STT may transcribe it as empty; the
  research signal is auditory prediction-error + salience, not words. Documented.)

### `PlaylistAudioStream`
- Reuses `load_playlist_manifest` + the **same** sha256 verification as the video
  playlist (shared `verify()` semantics; a digest mismatch fails closed). The
  manifest is the single source of truth for both surfaces.
- Decodes the **audio track** of each media file in manifest order. cv2 cannot
  decode audio, so this uses **PyAV** (`import av`) to pull audio frames, resample
  to `sample_rate`/`channels`, and emit PCM blocks. If `av` is unavailable it
  raises `PerceptionUnavailableError` with an install hint (mirror the cv2 path) —
  honest failure, never a silent no-op or synthetic substitute.
- Persists nothing beyond the manifest it is handed (zero-persistence).

## Audition plumbing

`Audition.__init__` gains `stream_factory: Callable[..., _AudioStream] | None`,
threaded into `_build_default_live_mic` → `LiveMicrophone(stream_factory=...)`.
This is the precise mirror of how Topos received `source_factory`. When a
deterministic mode is selected, `make_audition` sets `capture_enabled=True` and
passes the factory, so the locus-gated supervisor reads from the deterministic
source instead of the mic.

## Synchronization — honest guarantee

Topos and Audition are separate modules with separate loops and cadences. We do
**not** claim frame-locked A/V sync. The guarantee is:

- **playlist:** both surfaces walk the *same ordered, checksummed manifest*, so
  picture and sound come from the same media, advancing clip-by-clip together —
  synchronized at the media/clip granularity.
- **seeded:** both procedural streams derive from the *same seed and a shared
  frame clock*, and surprise events fire on *shared cadence slots* — coherent and
  cross-modally bound by construction, without inter-loop frame locking.

The spec and docs state this explicitly so nothing over-claims (no pretend sync).

## Covariate

`gather_perception_feed_descriptor` extends to the unified feed:
`{mode, seed, video: <schedule>, audio: <schedule>}` for seeded, and the shared
`{mode, playlist: <manifest sha256 + per-item digests>}` for playlist (one
manifest covers both surfaces — no duplication). Stays at the boot layer
(import-boundary contract) and remains best-effort (never crashes boot).

## Zero-persistence

The audio sources never open a file for writing; PCM lives only in the bounded
queue and is released after each sink call, exactly like the live mic. The
build-time zero-persistence guard (`tests/test_zero_persistence_invariant.py`)
extends to `kaine/modules/audition/feed.py`.

## Boundaries

`kaine.boot` is the only layer that imports `kaine.modules.*` to build factories
and the descriptor; `kaine.experiment` receives the descriptor as data (unchanged
contract). New module code stays within `kaine.modules.*`. `lint-imports` must
stay green.
