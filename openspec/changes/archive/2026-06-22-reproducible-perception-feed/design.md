# Design — reproducible-perception-feed

## The seam already exists

`kaine/modules/topos/live.py` defines:

```python
class _VideoSource(Protocol):
    def open(self) -> bool: ...
    def read(self) -> tuple[bool, Any]: ...   # (ok, BGR ndarray)
    def release(self) -> None: ...

class LiveCamera:
    def __init__(..., source_factory: Callable[..., _VideoSource] | None = None): ...
```

The default factory wraps `cv2.VideoCapture`. A deterministic feed is just another
`source_factory`. No new perception architecture is needed — the change supplies new
sources and the config to select them, and the existing BGR→RGB→PIL→`process_frame`
path, habituation, change-detection, and the zero-persistence AST guard all apply
unchanged.

## Two requirements pull in tension — and how the seed resolves them

The research wants the stimulus to be **reproducible** (same run → same stream, so
results replicate) AND **surprising to the entity** (so prediction error is
non-trivial and the world model has something to learn). Naively these conflict: a
fully reproducible stream is, in principle, fully predictable.

The resolution the operator named: make surprise a **deterministic function of a
seed the entity does not have and cannot recover from the pixels**.

- The frame at index `i` is `frame(seed, i)` — a pure function. Re-running with the
  same `seed` yields the identical stream, bit-for-bit. → **reproducible.**
- The stream has two layers:
  - a **structured base signal** (e.g. slow continuous drifts / periodic motion)
    that *is* learnable — as the world model fits it, prediction error on the base
    falls. This is the genuine-learning signal the loop needs.
  - **surprise events** injected at indices and with content chosen by a
    **counter-based PRNG** keyed on `seed` (e.g. `prng = hash(seed, i)` style, a
    stateless splittable generator). The schedule and content are fixed given the
    seed, but to *anticipate* the next surprise the entity would have to invert the
    keyed hash from observed frames — computationally infeasible. → **not
    predictable to the entity**, while still reproducible for the experimenter.

"Set intervals" from the operator's message can be literal (surprise every N frames,
content seeded) or seeded-jittered intervals; both are reproducible. The defaults
make the *cadence* regular (so the experiment is legible) and the *content/onset
detail* seed-driven (so it stays genuinely surprising). The exact base-signal family
and surprise repertoire are build-time choices; the spec constrains the *properties*
(pure-function determinism + keyed-PRNG surprise + no entity-predictability), not the
art.

## Why a counter-based / stateless PRNG (not `random`)

`random.Random(seed)` is sequential — reproducible only if every frame is generated
in order with no skips, which is fragile under restarts/seeks. A **counter-based**
generator (`value = keyed_hash(seed, frame_index)`) is reproducible *and*
seekable/restart-safe: frame `i` is the same regardless of path taken to it. It also
makes the "entity can't predict" property crisp: predicting surprise = inverting a
keyed hash. (Note: scripts in this codebase can't call `random`/`Date.now` for
reproducibility reasons anyway; a counter-based scheme is the right primitive.)

## PlaylistSource — operator media, made scientific

A `PlaylistSource` reads a **manifest** the operator authors:

```toml
# perception_playlist.toml  (operator-supplied; copyright-free media)
[[item]]
path = "clips/forest_walk.mp4"
sha256 = "…"          # pins the exact file
fps = 30              # frame timing → reproducible frame indexing
[[item]]
path = "clips/city_timelapse.mp4"
sha256 = "…"
fps = 30
```

`open()` verifies every `sha256` before the run; a mismatch fails the source
(reproducibility is void if the media changed). Order + fps make frame `i`
well-defined across runs. The operator does the copyright-free sourcing; the manifest
+ checksums make any given playlist a reproducible artifact. The manifest digest is
the covariate recorded for the run.

## Covariate

The run's research submission manifest records the feed descriptor:

- `mode = "seeded"` → `{seed, schedule_params}` (enough to regenerate the stream);
- `mode = "playlist"` → `{manifest_sha256, item_digests}` (enough to verify the
  stream).

So another researcher can reproduce or verify the exact perceptual input, the same
way the abliterated-organ change records the model provenance.

## Zero-persistence

The seeded source synthesizes frames in memory and hands them to `process_frame`
exactly like the camera; it persists only `(seed, schedule)`, never rendered pixels.
The playlist source decodes media to in-memory frames; it persists nothing beyond the
manifest it was given. The existing AST guard that fails the build on a frame-writing
call continues to cover both. This keeps the eyes-and-ears invariant: perception is
live, raw sense-data is never stored.

## Config

```toml
[topos.perception_feed]
mode = "off"                 # "off" | "seeded" | "playlist" | "camera"; shipped off
seed = 0                     # seeded mode: stream is a pure function of this
surprise_interval = 150      # base cadence of surprise events (frames)
surprise_strength = 1.0      # magnitude knob for surprise content
playlist_manifest = ""       # playlist mode: path to the checksummed manifest
```

Shipped `off`; a research boot sets `seeded` (recommended) or `playlist`. `camera`
is the existing live path (non-reproducible; for operator-present demos only). No
module flag flips → the all-off first-boot guard is unaffected.

## Recommendation

Make **`seeded`** the canonical research stimulus: self-contained, copyright-free,
bit-identical per seed, restart-safe, and purpose-built for the prediction loop. Keep
**`playlist`** as the operator-curated naturalistic alternative for runs where
real-world media is the point — reproducible once the operator pins the manifest. Both
ship; neither blocks the other.

## Alternatives considered

- **Just point `capture_device` at a video file** (cv2 accepts a path). Works as a
  quick hack but isn't reproducible (no checksum, decoder/timing drift) and offers no
  controlled surprise schedule. The `PlaylistSource` is this done properly.
- **Pre-render the seeded stream to a file and ship it.** Reintroduces a media asset
  to license/store and loses seekability/parameterization. The generator is smaller
  and more flexible than its output. Rejected.
- **Live human/camera input.** Explicitly excluded by the reproducibility rule;
  retained only as the operator-present `camera` mode for demos.

## Risks

- **Seeded stimulus too synthetic to drive rich cognition.** Mitigated by the
  playlist path for naturalistic media; and the base-signal repertoire can grow. The
  generator is the *floor* that unblocks research, not a ceiling.
- **Surprise accidentally predictable.** Use a cryptographically-keyed counter PRNG
  so inversion is infeasible; test that successive seeds produce decorrelated
  schedules.
- **Playlist manifest drift.** sha256 verification fails closed on any media change.
