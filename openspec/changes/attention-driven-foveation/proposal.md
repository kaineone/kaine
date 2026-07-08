# Attention-driven foveation for screen perception

## Why

Screen perception currently scales the whole screen to Topos's fixed capture
geometry — a uniform downsample. A shared 4K screen rendered to 640×480 loses fine
detail *everywhere*: text, small UI, a game HUD, a face in a video. Raising the
global capture resolution raises both the streamed data and the per-frame encoder
cost roughly linearly, against a tight ~100 ms processing tick.

Biology does not spend resolution uniformly. A small high-acuity fovea carries
detail, the periphery is coarse, and the eye *saccades* to move the fovea to what
matters. Foveated rendering applies the same idea to save bandwidth and compute.
Gaze-tracked systems need eye-tracking hardware to know where "you" are looking;
**KAINE does not — the *where* already exists internally, as the workspace's own
attention.** Foveation can therefore be driven by cognition directly, which turns
it from a one-way capture optimization into a genuine perception–action loop.

This is the architecture's own machinery applied *spatially*: precision-weighted
attentional selection (already in Syneidesis), forward-model prediction error
(already in Topos), and epistemic action valued by expected free energy (already
in Nous). Moving the fovea to reduce uncertainty is textbook active vision —
saccades as experiments (Friston et al. 2012). Two properties fall out for free:
publishing the fovea location (and a *predicted* next fovea) is a concrete
**attention schema**, an indicator the paper (§5) currently marks "not implemented
in the full sense"; and the same fovea-target signal is the screen-perception
analog of the "gaze direction decoupled from the body" scalar the paper's §3.4.6
Mundus plan already names — one attention mechanism, two effectors.

This is a **design-first** OpenSpec change. It specifies the mechanism; it does not
implement it. The lead reviews this design before any code lands.

## What Changes

- **Topos gains a coarse spatial saliency map.** In addition to today's whole-frame
  salience scalars, Topos computes a low-resolution per-tile map of change /
  forward-model prediction error over the current frame — *where* on the frame is
  surprising, not just how surprising the frame is. This is a modest extension of
  the existing per-frame scoring, and it never leaves memory.
- **A fovea target is selected by precision-weighted competition.** The bottom-up
  saliency argmax combines with an optional top-down bias (a goal- or agent-driven
  region from the workspace / Nous / Empatheia) under precision weighting — the same
  precision-as-attentional-gain the architecture already uses. Thymos arousal sets
  the fovea *size* ("arousal widens the attentional window," §3.4.3): wide and
  low-magnification under high arousal, tight and high-magnification under focus.
- **Two views per tick: peripheral + foveal.** From a single moderate-resolution
  screen grab held in memory, Topos derives a downsampled peripheral view (whole
  field, coarse gist) and a foveal crop around the target scaled to the encoder's
  native patch. Both are encoded; the report carries both latents plus the fovea
  location. Optionally (Phase 3) a second native-resolution region capture, pinned
  to the fovea and re-pinned only on a **saccade** (move past a hysteresis
  threshold after a minimum dwell), supplies true-native fovea detail without
  paying capture reconfiguration every tick.
- **The fovea location is published as a content-free signal.** Normalized
  coordinates and the fovea size only — never pixels — so the workspace, the
  self-model, and diagnostics know *where* the entity is attending, and a forward
  model can predict the next fovea (the attention schema).
- **The zero-raw-sense-data invariant is preserved.** The moderate-resolution grab,
  the peripheral downsample, and the foveal crop live only in process memory and
  are released as they age out; nothing is written to disk, exactly as the existing
  perception path guarantees.

## Capabilities

### New Capabilities

- `topos-foveation`: spatial saliency mapping over the current frame; precision-
  weighted fovea-target selection combining bottom-up saliency and optional
  top-down bias, with arousal-set fovea size; production of a peripheral view and a
  foveal crop from a single in-memory grab; saccadic hysteresis for any native
  region re-capture; and publication of the content-free fovea location and a
  predicted next fovea (attention schema).

### Modified Capabilities

- `topos`: the `topos.report` carries a peripheral latent, a foveal latent, and the
  content-free fovea location, rather than a single whole-frame latent, when
  foveation is enabled; whole-frame salience remains available as a diagnostic and
  as the fallback when foveation is off. The frozen-encoder and zero-persistence
  properties are unchanged.

## Impact

- **Depends on:** `topos`, `topos-predictive` (the forward-model prediction error
  that drives the spatial map), `reproducible-perception` (the screen/live capture
  path the two views are derived from), `oscillatory-binding` (precision weighting
  in Syneidesis for the bottom-up/top-down combination), `entity-time` (the
  two-clocks cadence the fovea updates on). All shipped.
- **Repo (at implementation time, not in this change):** would touch
  `kaine/modules/topos/module.py` and the salience/forward-model path (spatial
  map + fovea selection + dual-view encode), the perception feed builders in
  `kaine/boot.py` (moderate-res grab + optional native region capture), config
  `[perception_feed]`/`[topos]`, and `docs/modules/topos.md`. No entity is booted
  by this change.
- **Encoder cost:** two small encodes (a downsampled peripheral + a native-size
  foveal patch) replace one large uniform encode — comparable or cheaper — but this
  MUST be confirmed on the host startup benchmark before enabling, not asserted.
- **Behavior:** effective acuity rises sharply at the attended region for bounded
  capture cost; vision becomes active (an internal epistemic-action loop). Off by
  default; the uniform path remains the shipped behavior until benchmarked.
- **Open operator decisions:** see `design.md` §Flags — capture-resolution ceiling;
  single-grab-crop vs the Phase-3 native region capture; whether Phase 1 ships
  bottom-up-only (no top-down); single vs top-k foveae.
