## Context

KAINE Phase 2.3 — the last Phase 2 module. Soma's interoception and
Chronos's temporal flow are in place; Topos adds spatial perception
through a frozen vision encoder. Build prompt §2.3 names V-JEPA 2 as
the preferred encoder and DINOv2 ViT-S/B as the fallback when V-JEPA 2
doesn't fit the RTX 3070's 8 GB budget. Both are Meta releases; both
are accessible via HuggingFace and don't require a gated download.

Constraints:
- All-local at runtime: weights are downloaded once, then offline.
- Frozen encoder: no training, no grad. Topos perceives, it does not
  learn.
- Latent vectors over the bus, not text descriptions. Matches the
  paper's framing of perception as a substrate that delivers
  representations, not labels.
- Encoder choice must be swappable. V-JEPA 2 ships behind the same
  `Encoder` protocol when KAINE has empirical evidence to pick it.

Stakeholders: Mnemos (Phase 3.2 will store latents tagged with
emotional context), Nous (Phase 3.1 can reason about objects given
embedding-space comparisons or future linear-probe heads), Nexus
diagnostics (Phase 8 visualizes change/habituation), Thymos (the
sense of "things changing too fast / not changing at all" feeds
arousal).

## Goals / Non-Goals

**Goals:**
- `Topos.process_frame(image)` accepts a PIL `Image`, numpy array, or
  raw bytes and publishes a `topos.report`.
- Default encoder is `facebook/dinov2-small` (22M params, 384-dim CLS
  output). Loaded once at initialize; frozen and eval-only.
- `CosineChangeDetector` reports `change_score = 1 - cos_sim(prev,
  current)` ∈ `[0, 2]` (cos_sim ∈ [-1, 1]). Salience elevates when the
  score exceeds a configured alert threshold.
- `RollingMeanHabituator` reports habituation in `[0, 1]`. The score
  rises as the recent frame mean stabilizes (low variance in the
  rolling window).
- Tests run without a real `transformers` download.

**Non-Goals:**
- Object detection, segmentation, OCR. Latents are the deliverable;
  task-specific heads land in later phases if needed.
- Video temporal modeling inside Topos. Chronos owns temporal flow.
  Topos is a per-frame transducer.
- A built-in frame source. Webcam / video-file adapters ship in a
  later change; Phase 2.3 just provides `process_frame`.

## Decisions

**DINOv2 ViT-S/14 as v1 default.** Build prompt names it as the
acceptable fallback when V-JEPA 2 doesn't fit. DINOv2 small is
22M params, ~85 MB on disk, runs comfortably on either GPU or CPU,
and is available without HF model-card gating. V-JEPA 2 ships behind
the same `Encoder` protocol when we have empirical reason to pick it
(VRAM measurement against actual concurrent Speaches+Chatterbox load).

**384-dim CLS embedding as the latent.** DINOv2 small returns a
(batch, num_patches+1, 384) tensor from its last hidden state. The
patch-zero token (CLS) is the image-level summary. We extract that
and emit it as `list[float]`. Average-pooled patch tokens are an
alternative; CLS is what DINOv2 was trained to use and produces
stronger image-level features in benchmarks.

**Encoder lives behind `Encoder` protocol.** `encode(image) ->
list[float]`. The async signature lets later encoders use
`asyncio.to_thread` for CPU encoding without changing callers. Topos
never touches torch directly — the encoder hides it.

**Device chosen by `select_device(preferred)`.** Operator picks via
`[topos].device` in `config/kaine.toml`: `cuda` (use whatever CUDA
device the host has), `cpu`, or `auto` (default — uses
`detect_device()`). On a multi-GPU host the operator can pin via
`KAINE_FORCE_DEVICE` if a specific GPU should host Topos. Future
config will allow `cuda:0` / `cuda:1` precision once the multi-GPU
allocator is built.

**Lazy import of transformers and torch.** Like Chronos, the package
imports cleanly without those installed; only `DINOv2Encoder.load()`
pulls them in. This keeps featurization/change/habituation tests fast.

**Image preprocessing inside the encoder, not the module.** The
encoder owns its `AutoImageProcessor` and accepts loose inputs
(`PIL.Image`, ndarray, bytes). The module sees only `encode(image)`
and a float vector back.

**`CosineChangeDetector` keeps the most recent embedding only.** No
window — change is "compared to the immediately previous frame" by
design. Habituation lives in its own module which does track a window.

**Habituation: rolling-mean L2 stability.** Maintain a deque of
recent embeddings (default window 16). Habituation score is
`1 / (1 + variance_of_pairwise_distances)`, mapped to `[0, 1]`. A
fully static scene → variance → 0 → habituation → 1. A constantly
changing scene → high variance → habituation → 0. Simple, monotonic,
no learning.

**`Topos.process_frame` is synchronous on the caller's perspective
but awaits the async `encode`.** It returns the published entry id so
callers can correlate. Tests assert one frame in → one publish out.

**Topos does NOT subscribe to a peer stream by default.** No frame
source on the bus today. When the future webcam adapter lands it
calls `topos.process_frame` directly from its own loop. The base
module workspace consumer is inherited unchanged so Topos still
participates in the experiential broadcast feedback loop.

## Risks / Trade-offs

- **transformers is ~1.5 GB with its deps.** → Documented; included
  in the dynamic install. Operators who shed Topos (Phase 7.3 module
  shedding) can also skip transformers if they pip-install KAINE
  without `[full]` — Phase 7 will add the optional-extra split.
- **CLS-only feature may miss spatial layout.** → Linear probes on
  patch tokens can be added later as a separate `Encoder` impl.
- **DINOv2 small on CPU is ~50–100 ms per frame.** → Acceptable for
  the experiential rate (3 Hz default). Operator can pin to GPU.
- **First-time HF download requires network.** Build prompt allows
  setup-time network; documented in SETUP.md.

## Migration Plan

First implementation. Topos is registered in code paths but not
auto-added to ModuleRegistry. The Phase 9 first-boot script wires it
up when the operator opts in.

Rollback: revert the commit. Phase 2 stays at Soma + Chronos and the
`v0.2-perception` tag waits.

## Open Questions

- Whether to ship V-JEPA 2 as a second `Encoder` default behind a
  config flag. Deferring until we have empirical VRAM measurements on
  this host under concurrent Speaches+Chatterbox load. Documented as
  "drop-in via the Encoder protocol" in the encoder module's
  docstring so it is a clear future change.
- Whether to default `[topos].device` to `auto` (detect) or `cpu`
  (safe everywhere). Choosing `auto` — the operator's hardware
  preference flows through `detect_device`/`select_device`, matching
  the dynamic-hardware capability.
