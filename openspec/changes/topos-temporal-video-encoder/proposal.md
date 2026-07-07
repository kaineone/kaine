# Replace the Topos vision encoder with a temporally-native video encoder (InternVideo-Next)

## Why

Two goals converge on one change.

**1. Remove the last Meta-owned model.** Topos's frozen vision encoder is
`facebook/dinov2-small` — the only Meta/`facebook`-namespaced model KAINE loads.
Every other model in the stack is already off Meta (the language organ is an
abliterated Qwen, embeddings are `all-MiniLM`, the world-model core is a
self-contained re-implementation of danijar/dreamerv3). Dropping DINOv2 removes
the project's sole dependency on a Meta artifact.

**2. Realize the paper's "temporally-native embeddings" future direction.**
`docs/tech-choices.md` §"Vision" already records the intended upgrade: the paper
(§10) identifies "a stronger self-supervised video encoder — one yielding richer,
temporally-native embeddings versus DINOv2's per-frame features — as a future
upgrade, kept vendor-neutral and dropping in behind the swappable `Encoder`
protocol." DINOv2 encodes one frame at a time and is blind to motion; the change /
habituation / prediction-error salience pipeline reconstructs temporal structure
only indirectly, from a sequence of independent per-frame vectors.

The operator chose the **temporal-video-encoder direction** (not a like-for-like
per-frame swap to another still-image model) and **design-first delivery** (this
change is design only; no encoder or runtime code is written here).

The target model is **InternVideo-Next base**
(`revliter/internvideo_next_base_p14_res224_f16`, OpenGVLab, CVPR 2026):
91M parameters, **MIT-licensed**, a temporally-native self-supervised video
encoder. It ingests a 16-frame clip and emits patch-token features that already
encode motion. It is an Encoder-Predictor-Decoder whose predictor is a latent
world model — but **this change uses only the frozen encoder as a feature
extractor**; KAINE's world model (Phantasia / DreamerV3) is untouched.

This is a design-first OpenSpec change. It specifies the swap; it does not
implement it. The lead reviews this design before any code lands.

## What Changes

- **Encoder seam becomes clip-native.** The `Encoder` protocol grows a
  `clip_len` property and an `encode_clip(frames) -> list[float]` method. Topos
  owns a RAM-only 16-frame ring buffer of recent frames and calls `encode_clip`
  on a configurable stride, so one **temporally-native** clip latent is produced
  per emitted tick instead of one per-frame latent. The zero-raw-sense-data
  persistence invariant is preserved: the ring buffer lives only in process
  memory, is never written to disk, and each frame is released as it ages out.
- **New default encoder: `InternVideoNextEncoder`.** A frozen (`eval()`,
  `requires_grad_(False)`) wrapper that mean-pools the `[1, 4096, 768]` feature
  tensor over its token axis to a single **768-dim** clip embedding. Loads a
  **vendored, revision-pinned** copy of the model — no `trust_remote_code`,
  nothing remote at runtime (see design.md §Security).
- **Clip cadence tied to the two-clocks timing model.** Frames enter the ring
  buffer at the subjective `vision_sample_hz` (10 Hz shipped). The clip latent is
  emitted every `clip_stride` frame-ticks; the shipped default aligns the clip
  cadence with the experiential / conscious-access rate (~3.33 Hz). The
  EntityClock dilation carries through unchanged because the stride is counted in
  frame-ticks.
- **Dim change 384 → 768, scoped.** The only hard-coupled consumer is Topos's own
  `LatentForwardModel`, whose input dim already derives dynamically from
  `encoder.latent_dim` — it becomes 768 with no code change. Phantasia's
  world-model `obs_dim` is **NOT** affected (it is a workspace-derived summary
  vector, not the Topos latent — see design.md §Dim cascade). Config, the
  real-encoder test, and docs move from 384 to 768. A forward-model checkpoint
  sized to the old dim is discarded with a warning (the model re-learns online).
- **Salience thresholds re-derived.** Change / habituation / prediction-error
  thresholds are tuned to DINOv2 feature statistics and to per-frame cadence;
  they are re-derived for the new encoder and overlapping-clip cadence via a
  short calibration pass on the seeded perception feed.
- **Vendored, pinned, offline modeling code.** The InternVideo-Next modeling code
  is vendored into `external/internvideo_next/` following the
  `external/dreamerv3/UPSTREAM` provenance convention (pinned commit SHA, MIT
  license text, vendoring-path decision). Weights are fetched once at setup time
  from the HF hub at the pinned revision into a local models dir; runtime loads
  them locally with `trust_remote_code=False`.
- **DINOv2 demoted, not necessarily deleted.** `facebook/dinov2-small` is removed
  as the shipped default and from the default config and docs, so a default
  install pulls no Meta weights. Whether the `DINOv2Encoder` class is kept in-tree
  as a selectable non-default Apache-2.0 fallback (clip_len=1) or deleted outright
  is **flagged for the operator** (design.md §Config & fallback).

## Capabilities

### Modified Capabilities

- `topos`: the encoder seam becomes clip-native; the shipped default encoder is
  the temporally-native InternVideo-Next (768-dim, MIT, vendored + pinned, no
  remote code); the `topos.report` `latent` is a 768-dim pooled clip embedding
  emitted at the clip cadence rather than a 384-dim per-frame CLS vector; the
  frozen-encoder security property is preserved and strengthened (no
  `trust_remote_code`); the default config carries no Meta model.
- `topos-predictive`: the visual forward model's latent dimension follows the
  encoder (768); a checkpoint whose dim does not match the running encoder is
  discarded with a warning rather than loaded, and the model re-learns online.

### New Capabilities

None. (No new module; the change modifies the existing `topos` and
`topos-predictive` capabilities.)

## Impact

- **Depends on:** `topos`, `topos-predictive`, `reproducible-perception` (the
  seeded feed used for threshold calibration), `dynamic-hardware` (device
  resolution), `entity-time` (two-clocks cadence). All shipped.
- **Repo (at implementation time, not in this change):** modifies
  `kaine/modules/topos/encoder.py`, `kaine/modules/topos/module.py`; adds
  `external/internvideo_next/` (vendored modeling code + `UPSTREAM`); updates
  `config/kaine.toml` `[topos]`, `docs/modules/topos.md`, `docs/tech-choices.md`,
  the opt-in real-encoder test, and `pyproject.toml`/extras if the vendored code
  needs `einops`.
- **Model licensing:** removes the `facebook/dinov2-small` (Apache-2.0, Meta)
  default; adds InternVideo-Next base (MIT, OpenGVLab). Net: off Meta.
- **Disk:** ~182 MB of fp16 weights fetched once at setup into a local models dir
  (git-ignored); no runtime fetch.
- **VRAM / compute:** 91M fp16 on `cuda:1` (~8 GB) fits comfortably. Per-clip
  cost is higher than DINOv2 per-frame (4096 tokens vs 256), which is why the
  clip cadence is strided to the experiential rate rather than run at the full
  10 Hz processing rate — see design.md §Clip cadence.
- **Behavior:** `topos.report` cadence drops from ~10 Hz to ~3.33 Hz (one
  temporally-native latent per emitted clip); the latent is 768-dim and
  motion-aware; salience thresholds are re-tuned. No entity is booted by this
  change.
