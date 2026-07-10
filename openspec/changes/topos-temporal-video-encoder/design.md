# Design — Topos temporally-native video encoder (InternVideo-Next)

This is a design-first change. No encoder or runtime code is written here; this
document records the decisions the implementation must follow, and flags the ones
the operator should rule on.

## Target model (given; not re-researched)

- `revliter/internvideo_next_base_p14_res224_f16` (HuggingFace), OpenGVLab's
  InternVideo-Next (CVPR 2026), **91M params, MIT license**.
- Loads via `transformers`: `AutoConfig` / `AutoModel.from_pretrained(...,
  trust_remote_code=True)` + `VideoMAEImageProcessor`.
- Inference: `model.extract_features(**inputs)` returns shape **`[1, 4096, 768]`**
  (hidden dim 768; 4096 = 16 frames × 256 patches at patch-14 / 224).
- Input: **16-frame clips**, 224×224, 3 channels, fp16. Fits `cuda:1` (~8 GB).
- Architecture is Encoder-Predictor-Decoder; the predictor is a latent world
  model. **This change uses ONLY the encoder** as a frozen feature extractor. The
  DreamerV3 world model (Phantasia) is unchanged and unrelated.

## Current system (what the swap has to preserve)

`kaine/modules/topos/`:

- `encoder.py` — the `Encoder` protocol (`model_id`, `latent_dim`, `load`,
  `encode(image) -> list[float]`, `shutdown`) and `DINOv2Encoder` (frozen,
  384-dim CLS token, one vector per frame).
- `module.py` — `Topos.process_frame(image)` runs, per frame: `encode` →
  `CosineChangeDetector.observe` (change_score = 1 − cosine(prev, cur)) →
  `RollingMeanHabituator.observe` (habituation = 1/(1+mean L2 to window mean)) →
  optional `LatentForwardModel.step` (L2 prediction error, normalized against a
  rolling mean; alert at ≥2× mean) → publishes `topos.report` with `latent`,
  `change_score`, `habituation_score`, `encoder_model_id`, `prediction_error`.
- `live.py` — `LiveCamera` captures one frame per subjective `capture_interval_s`
  (= 1/`vision_sample_hz`, 10 Hz shipped), converts BGR→in-memory PIL.Image, hands
  it to `process_frame`, and drops it. **Zero-persistence invariant**: no frame is
  written to disk (enforced by the static grep in
  `tests/test_zero_persistence_invariant.py`).
- `forward.py` — `LatentForwardModel(latent_dim=encoder.latent_dim, ...)`: a
  shallow CPU MLP over `[latent ‖ buffer_mean]` (input dim `2*latent_dim`). The
  latent dim is taken from the encoder at `initialize()` — nothing hardcodes 384.

Two-clocks timing (`entity-time`): the **processing rate** (10 Hz) is the
frame-sampling cadence; the **experiential / conscious-access rate** (~3.333 Hz,
P3b) is the workspace-broadcast rhythm. The EntityClock dilates both together with
`time_scale`.

## Problem 1 — Per-frame → 16-frame clip

DINOv2 turns one frame into one vector each tick. InternVideo-Next needs a
16-frame clip. Two questions: **where the clip lives** and **how often it is
encoded**.

### 1a. Seam: Topos owns a RAM-only frame ring buffer

**Decision.** Extend the `Encoder` protocol with:

- `clip_len: int` — the number of frames the encoder consumes (16 for
  InternVideo-Next; 1 for a per-frame fallback).
- `async encode_clip(frames: Sequence[image]) -> list[float]` — encode a clip of
  exactly `clip_len` frames to one pooled vector.

`Topos` keeps a `collections.deque(maxlen=clip_len)` of the most recent frames.
`process_frame` appends the incoming PIL.Image, and — when the buffer is full and
the stride fires — calls `encode_clip(list(buffer))`, runs the salience pipeline,
and publishes. This puts cadence control in Topos (which already owns the
salience state) and keeps the encoder a pure clip→vector function.

**Zero-persistence.** The ring buffer is an in-memory deque of PIL.Images; it is
never serialized (`Topos.serialize` already emits only weights + statistical
summaries) and never written to disk. Each frame is dropped when it ages out of
the bounded deque, exactly as a single frame is dropped today. The existing
`tests/test_zero_persistence_invariant.py` grep continues to guard the module.
The design MUST add an explicit "the frame ring buffer is RAM-only, never
persisted" note at the buffer site and a test asserting the buffer is absent from
`serialize()` output.

### 1b. Clip cadence: strided sliding window, tied to the experiential clock

**Options.**

- **Sliding window, stride = 1** — encode the last 16 frames every tick. One clip
  latent per frame-tick → the `topos.report` cadence stays at 10 Hz. Consecutive
  clips overlap by 15/16 frames, so the change signal is fine-grained. Cost: one
  91M forward over 4096 tokens **per tick, at 10 Hz** on the shared `cuda:1`. A
  4096-token ViT forward is ~16× the token count of DINOv2-small's 256 and
  attention is O(n²); sustaining 10 Hz is the doubtful case on an 8 GB secondary
  GPU that also hosts TTS.
- **Non-overlapping windows, stride = 16** — a clip latent only every 16 frames ≈
  **1.6 s** at 10 Hz (~0.625 Hz). Cheapest, but salience becomes coarse: change /
  habituation / prediction-error now compare scenes 1.6 s apart, losing sub-second
  novelty. Each latent is still internally motion-aware, but the *reactivity* of
  the perception loop collapses.
- **Strided sliding window (recommended)** — encode the last 16 frames every
  `clip_stride` ticks. `clip_stride = 3` at 10 Hz emits a clip latent every 0.3 s
  ≈ **3.33 Hz**, which aligns the temporally-native visual percept with the
  **experiential / conscious-access rate** (P3b 3.333 Hz). Consecutive clips
  overlap by 13/16 frames, so change detection still sees fine motion inside each
  clip and smooth scene evolution across clips; GPU load is 3.33 forwards/s (a
  third of the sliding-stride-1 worst case).

**Recommendation: strided sliding window, default `clip_stride = 3`**, so the clip
latent cadence ≈ the experiential rate. Rationale:

1. **It resolves the two-clocks tension cleanly.** The fast processing clock
   (10 Hz) fills the ring buffer — that is exactly what a fast sensory sampling
   rate is *for*. The temporally-native latent, which is the entity's coherent
   *visual percept*, is produced at the conscious-access rate. This is a more
   faithful mapping of "senses run fast underneath a slow tick" than DINOv2's
   accidental one-latent-per-sample.
2. **It bounds GPU cost** to a benchmarked, sustainable rate on the shared 8 GB
   device (mirroring how `vision_sample_hz = 10` was "benchmarked-cleared" before
   shipping).
3. **EntityClock dilation is automatic** — the stride is counted in frame-ticks,
   which already dilate with `time_scale`, so the clip cadence dilates coherently
   with no extra clock wiring.

`clip_stride` is a config knob; the exact default is subject to the shakedown
benchmark (see §Flags). A warmup gap exists: no `topos.report` is published until
the ring buffer first fills (16 frames ≈ 1.6 s at 10 Hz). This is acceptable and
must be documented; the spec requires the first report only *after* the buffer
fills.

**Behavior change to record:** `topos.report` cadence drops from ~10 Hz to
~3.33 Hz. Consumers (workspace coalition, `prediction_error_observer`,
`research_event_observer`) are event-driven and tolerate the lower rate; none
assume a fixed 10 Hz. The lower, motion-aware cadence is the intended improvement,
not a regression.

## Problem 2 — Pooling `[1, 4096, 768]` → one 768-dim clip embedding

`extract_features` returns 4096 patch tokens × 768 dims and (per the given facts)
no dedicated CLS/global token is guaranteed.

**Decision: mean-pool over the 4096-token axis → a single 768-dim vector.**

Rationale:

- DINOv2 used the CLS token as a *global* scene descriptor. With no CLS token
  available, the standard global descriptor for a patch-token transformer is the
  mean over tokens — it summarizes the whole spatiotemporal field, which is
  exactly the role Topos needs (a stable global scene+motion signature for
  novelty / change / habituation, not localized patch queries).
- Mean-pooling jointly over space and time keeps the temporal information the
  encoder produced (tokens from all 16 frames contribute), which is the entire
  point of moving to a video encoder.

**Do NOT L2-normalize the pooled vector.** `CosineChangeDetector` is already
scale-invariant (cosine), so normalization would not help it; but
`RollingMeanHabituator` uses raw L2 distance, and the forward-model prediction
error is raw L2 — both carry signal in the vector's magnitude. Normalizing would
throw that away. (This is a minor decision — see §Flags — but the recommendation
is: leave the pooled features un-normalized and re-tune thresholds instead.)

The pooling method is a config value (`pooling = "mean"`), leaving room to try
attention-pooling later behind the same seam.

**Note discovered during the predictor-gate verification (§8):** the vendored
`modeling_internvideo_next.py` includes an `AttentionPoolingBlock`
(`attn_pool_num_heads = 16`, `clip_embed_dim = 768`) — the model has a **native
attention-pooling head** producing a CLIP-aligned 768-d global vector. If, at
vendoring time, that pooled output is cleanly reachable (a method or a second
head alongside `extract_features`), **prefer the native attention-pooled vector**
over manual mean-pooling: it is what the model was trained to summarize a clip
with, and it is still 768-d (no cascade impact). The implementation should check
this and fall back to mean-pool only if the native pool is not exposed; expose
the choice as `pooling = "attention" | "mean"`.

## Problem 3 — Dim cascade 384 → 768 (enumerated)

The task brief assumed Phantasia's world model would need re-dimensioning. It does
**not** — this is the key finding that scopes the change down.

| Consumer | Assumes 384? | What changes |
|---|---|---|
| `topos/encoder.py` new encoder | probes at load | reports `latent_dim = 768` from a dummy forward, same as DINOv2 probes 384 today. |
| `LatentForwardModel` (`topos/forward.py`) | **no** — `latent_dim=encoder.latent_dim` | input dim becomes `2*768 = 1536`, hidden `units`, output 768 — **all derived, no code change**. Per-frame CPU cost doubles (O(dim) Python loops for buffer mean) but stays trivial at 3.33 Hz. `forward_model_units` default may be raised (128→256) so hidden width isn't a bottleneck for a 768-d target — a tuning choice, not a correctness one. |
| Topos snapshot (`serialize`/`deserialize`) | forward-model weights sized to old dim | a 384-sized forward-model checkpoint cannot load into a 768 model. `deserialize` MUST detect the shape mismatch and **discard** the forward-model weights with a warning (the model re-learns online from scratch — it is an online adapter, this is safe). Today `deserialize` only logs an encoder-id mismatch; it must also guard the forward-model tensor shapes. |
| **Phantasia world model `obs_dim` + RSSM `obs_dim`** | **NO — decoupled** | `kaine/modules/phantasia/encoder.py`: `OBS_DIM = len(SOURCE_ORDER) + 3 + 1 = 19`. The observation vector is a per-source **salience-weighted coalition summary + affect + inhibition flag** — it never contains the Topos latent. Phantasia reads Topos's *salience contribution to the workspace*, not its 384/768 vector. **The world model, its RSSM dims, and its weight checkpoints are unaffected by this change.** No re-learn is forced on Phantasia. |
| Mnemos vector store | independent 384 (text) | Mnemos indexes `all-MiniLM` text embeddings (384), not Topos visual latents. No wiring currently routes `topos.report.latent` into a vector store, so nothing there changes. (Docs' "Mnemos may store these latents" is aspirational, not wired.) |
| Evaluation observers (`prediction_error_observer`, `research_event_observer`, `log_schema`) | no | they read `prediction_error` / `horizon` scalars from `topos.report`, never the `latent` — dim-agnostic. |
| Faithful renderer `_t_topos_report` | no | renders `change_score` / `habituation_score` / `encoder_model_id` — dim-agnostic. |
| `config/kaine.toml` `[topos]` | doc/value | model id, revision, clip params, pooling, and re-tuned thresholds change; no dim literal is stored today. |
| Real-encoder test (opt-in, `KAINE_TOPOS_RUN_REAL_ENCODER=1`) | asserts 384 CLS | update to assert a 768-dim pooled clip vector from a 16-frame clip. The fake-encoder unit tests use small deterministic vectors and are dim-agnostic — unaffected. |
| Docs (`docs/modules/topos.md`, `docs/tech-choices.md`) | "384-dim" | update to 768-dim temporally-native clip embedding; rewrite the DINOv2 section. |

Net: the real cascade is **the forward model input (auto), one snapshot guard,
config, the real-encoder test, and docs.** Phantasia is out of scope.

## Problem 4 — Salience re-tuning

The change / habituation / prediction-error thresholds are calibrated to DINOv2
feature statistics *and* to per-frame cadence. Both shift:

- **Cosine change scale** differs for a different encoder's feature geometry.
- **Overlapping clips** (13/16 shared frames at stride 3) make consecutive
  latents more correlated than consecutive DINOv2 per-frame vectors were, which
  *lowers* typical change_score — so `change_alert_threshold = 0.5` will likely
  be too high and must come down.
- **Habituation L2 scale** depends on the (un-normalized) pooled-feature
  magnitude — different from DINOv2 CLS.
- **Prediction-error** normalization is self-scaling (ratio to rolling mean), so
  the `≥ 2.0×` alert factor is more robust, but should still be re-checked.

**Decision.** Treat all Topos salience thresholds as **encoder-and-cadence
dependent** and re-derive them with a short **calibration pass on the seeded
perception feed** (`reproducible-perception` provides a deterministic, replayable
stimulus). Procedure the implementation follows:

1. Run the new encoder over the seeded feed at the shipped `clip_stride` for a
   fixed window with `forward_prediction` on.
2. Record the distributions of `change_score`, `habituation_score`, and
   normalized prediction error.
3. Set `change_alert_threshold` to a high percentile (e.g. ~90th) of the observed
   change distribution so routine motion stays baseline and genuine scene cuts
   alert; sanity-check `baseline_salience` / `alert_salience` behavior.
4. Commit the derived values into `[topos]` and record the calibration window +
   feed seed as provenance (a research covariate, consistent with
   `reproducible-perception`).

Config keys affected: `change_alert_threshold` (re-derived), and the calibration
is documented; `baseline_salience` / `alert_salience` likely unchanged but
re-verified. This is a controlled re-derivation, not a guessed constant (no
cheap fixes).

## Problem 5 — Security: eliminate `trust_remote_code=True`

`AutoModel.from_pretrained(..., trust_remote_code=True)` executes the model repo's
Python on load. That is a supply-chain execution path that conflicts with KAINE's
local-only / no-cloud stance and would **weaken** the load-bearing security
property that a *frozen* encoder gives an attacker no fine-tuning foothold: remote
code at load is a foothold of a different kind.

**Decision: vendor the modeling code, pin the revision, load with
`trust_remote_code=False`.**

1. **Vendor** the InternVideo-Next modeling code (the `modeling_*.py`,
   `configuration_*.py`, and processor glue the repo ships) into
   `external/internvideo_next/`, following the established
   `external/dreamerv3/UPSTREAM` convention:
   - an `UPSTREAM` file recording the upstream repo, the **pinned commit SHA**,
     the MIT license text, and the vendoring-path decision (literal-source vendor
     vs. faithful re-implementation — for a modeling file the literal vendor is
     appropriate, unlike dreamerv3's research-infra tangle);
   - `SPDX-License-Identifier: MIT` headers and attribution.
2. **Register** the vendored `InternVideoNextConfig` / model classes explicitly
   and instantiate them directly, loading the pinned local safetensors — so
   `from_pretrained` runs against a **local directory** with
   `trust_remote_code=False` and no code is fetched or executed from the hub at
   runtime.
3. **Pin the revision.** Config carries `encoder_revision = "<commit SHA>"`; the
   setup-time weight fetch pins the same SHA. A mismatch between the vendored code
   revision and the weight revision is a load-time error.
4. **Auditable offline.** The vendored code is reviewed once at vendoring time and
   is diffable in-repo forever after; nothing about the runtime path depends on
   the network or on remote-code trust.

This preserves and *strengthens* the "frozen encoder removes an attacker's
fine-tuning pathway" property: frozen weights + no remote code + pinned revision.

The frozen contract is unchanged from DINOv2: `eval()`, `requires_grad_(False)`
on every parameter, Topos never calls `.train()`/an optimizer on the encoder.

## Problem 6 — Config & fallback (flagged)

The operator wants off Meta. Two sub-decisions:

- **Default:** InternVideo-Next becomes the shipped default; `encoder_model_id`
  becomes the InternVideo-Next id and `facebook/dinov2-small` is removed from the
  default config and docs. A default install then pulls **no Meta weights**. This
  is required to actually meet the goal and is not in question.
- **DINOv2 class:** whether to (a) **delete** `DINOv2Encoder` entirely, or (b)
  **keep** it in-tree as a **selectable non-default** per-frame fallback
  (`encoder_backend = "dinov2"`, `clip_len = 1`, `encode_clip` encodes the last
  frame) behind the unified protocol.

**Recommendation: (b) keep DINOv2Encoder as a non-default, non-shipped fallback,
but strip `facebook/dinov2-small` from the shipped config and docs.** It is a
proven, tiny, Apache-2.0 encoder that costs nothing at rest (a class + a constant,
no weights fetched unless explicitly selected), and keeping the protocol
demonstrably multi-encoder is good architecture and useful for regression
comparison. Removing it buys ideological purity at the cost of a proven fallback.
Because "off Meta" means *nothing Meta is fetched or loaded by default* — which
(b) already achieves — the safer choice is to keep the escape hatch. **This is
the operator's call** (see §Flags).

A `encoder_backend` selector (`"internvideo_next"` default; `"dinov2"` optional)
makes the choice a config edit, not a code change.

## Problem 7 — Offline availability / weights

- **Fetch once at setup.** ~182 MB fp16 (91M params) pulled from the HF hub at
  the pinned `encoder_revision` into a local models dir (git-ignored, e.g.
  `models/internvideo_next/`) by a setup step, consistent with the no-cloud
  **runtime** rule (setup-time downloads are permitted; this one is free and
  one-time). `HF_HUB_DISABLE_TELEMETRY=1` is set before any hub call, matching the
  existing encoder loader.
- **Runtime is fully local.** Loads from the local dir + vendored code; no network
  access at runtime.
- **Deps.** `transformers` and `torch` are already core; `VideoMAEImageProcessor`
  ships in `transformers`. Frames are handed in as in-memory PIL.Images, so no
  video-decoder dep (`decord`/`av`) is needed for the encoder path. If the
  vendored modeling code imports `einops`, declare it in the existing
  `[vision]`/vision extra (parity with how dreamerv3 declares `einops`/`chex`).

## Problem 8 — Option: adopt InternVideo-Next's predictor as the Topos forward model

InternVideo-Next is described as an Encoder-Predictor-Decoder; the predictor "P"
is a latent world model over the encoder's own visual latents. The operator asked
whether that predictor could **replace `LatentForwardModel`** — the module-level
visual next-latent predictor that emits Topos's forward-model prediction-error
salience. Evaluated here as an **option**, not a foregone choice.

### Scope: this matches the Topos forward model ONLY — never Phantasia

The predictor, if usable, is a **vision-only** next-*visual*-latent model. That is
exactly the role of `LatentForwardModel` (module-level visual prediction). It is
**not** a candidate to replace **Phantasia's DreamerV3 RSSM**, and cannot be one:
Phantasia predicts the whole-**workspace fused state** — a summary of
interoception (Soma) + timing (Chronos) + audio (Audition) + affect (Thymos) +
vision + inhibition (the 19-dim `obs_dim` vector) — and emits the **global**
surprise signal. A vision-only predictor has no access to those channels and
structurally cannot produce that signal. **Phantasia stays DreamerV3.** Nothing in
this option touches it. Anyone reading this must not conflate the two predictors:
Topos-forward = local visual surprise; Phantasia-RSSM = global multimodal surprise.

### Gate (VERIFIED): the published checkpoint is encoder-only → option INFEASIBLE as-is

The gate is: does the predictor expose a clean standalone interface (encoder
latents → predicted next latent)? Verified against the model repo
(`revliter/internvideo_next_base_p14_res224_f16`):

- `modeling_internvideo_next.py` defines only encoder machinery —
  `PatchEmbed`, `Attention`/`FlashAttention`/`Block`, `InternVideoNextBackbone`,
  the `InternVideoNext` `PreTrainedModel` wrapper, and an `AttentionPoolingBlock`.
  Public methods are `forward` / `extract_features` (+ pos-embed helpers). **There
  is no predictor class, no decoder, and no `predict()` / next-latent method.**
- `config.json` carries **exclusively encoder fields** (depth 12, embed_dim 768,
  num_frames 16, patch 14); no predictor/decoder config.
- `model.safetensors` (182 MB) contains encoder weights only.

The Predictor "P" and Decoder "D" of the Encoder-Predictor-Decoder are the
**training-time apparatus** and are **not distributed** in this published base
checkpoint. **Therefore the option is infeasible with the available weights** —
there is no predictor to adopt. Realizing it would require obtaining or training a
separate predictor head (not published; out of scope for this change and against
the design-first, no-invented-work posture).

**Decision: keep `LatentForwardModel` (the current small online-adapting head).**
The encoder swap stands alone; the predictor option is recorded as closed-unless-a
-predictor-checkpoint-appears.

### If a predictor checkpoint later becomes available — the analysis that would apply

Recorded so the operator can reopen this cleanly, not to act on now:

1. **Interface** — would still need to expose encoder-latents → next-latent
   standalone; re-run this gate against that release.
2. **Individuation / welfare posture (not just engineering).** A **frozen
   pretrained** predictor is a *different stance* from KAINE's experiential-
   learning / individuation values: the current head grows the entity's visual
   world model **from the entity's own experience**. Dropping in a fixed prior
   trained on someone else's video corpus imports a foreign world model. If ever
   adopted, the recommended shape is **frozen pretrained prior + a small online
   residual/head** so the entity still adapts on top of the prior — a warm start,
   not a replacement for lived learning. This has welfare/philosophy weight and is
   the operator's call, not an engineering default.
3. **Salience scale/character.** A pretrained predictor's prediction error would
   sit on a different scale and have a different character (low error on
   in-distribution motion, spikes on out-of-distribution scenes) than the current
   from-scratch head — it folds into the same re-tuning already in scope (§4), but
   would need its own calibration pass.
4. **Coupling cost.** Using the predictor would **deepen the tie to
   InternVideo-Next internals**, partially defeating the swappable-`Encoder`-
   protocol goal: today the encoder is a pure clip→vector function behind the
   protocol; adopting its predictor would pull model-specific latent-space
   structure into the salience path and make a future encoder swap much harder.
   This argues for keeping the predictor *out* even if one becomes available,
   unless its accuracy gain is large.

## Consequences

- Topos publishes a **motion-aware** 768-dim latent at ~3.33 Hz; the salience
  pipeline is unchanged in shape but re-tuned in constants.
- The project has **no Meta-owned model** in its default configuration.
- The forward model re-learns on first boot after the swap (online, expected);
  Phantasia is untouched.
- One more vendored third-party module (`external/internvideo_next/`) to keep
  provenance-pinned, in exchange for eliminating a `trust_remote_code` runtime
  path.

## Operator decisions (LOCKED 2026-07-06)

All five flags below are **DECIDED**; the recommendations were accepted. One
sequencing constraint was added at implementation time to honor "no pretend
processes": the shipped default is **not** flipped to InternVideo-Next until its
forward pass is genuinely implemented. Implementation is therefore **phased** —
**Phase 1** vendors the code, ships the offline-weights fetch, the no-remote-code
loader, and the `encoder_backend` selector (default stays `dinov2`, a real working
encoder); **Phase 2** implements the real clip pipeline and only then flips the
default. Selecting `internvideo_next` before Phase 2 raises a loud
`NotImplementedError` (never a fake embedding).

1. **DINOv2: KEEP** (§6) as a non-default, non-shipped fallback behind
   `encoder_backend`. InternVideo-Next becomes the shipped default and
   `facebook/dinov2-small` is stripped from the shipped config + docs — **in
   Phase 2**, once the encoder is real. Phase 1 keeps `dinov2` as the default.
   **DECIDED.**
2. **`clip_stride = 3`** (§1b, ≈ experiential 3.33 Hz), **provisional** pending a
   shakedown GPU benchmark on the secondary GPU — same "benchmark before ship"
   gate that cleared `vision_sample_hz = 10`. **DECIDED.**
3. **Do NOT L2-normalize** the pooled vector (§2) — keep the
   habituation/prediction-error magnitude signal; re-tune thresholds instead.
   Prefer the native attention-pool if reachable, else mean. **DECIDED.**
4. **`forward_model_units` 128 → 256** (§3) for the 768-d target. Pure tuning.
   **DECIDED.**
5. **Predictor NOT adopted / option CLOSED** (§8). Verified: the published
   checkpoint is encoder-only (a single `model.safetensors`; no predictor/decoder
   class, config, or weights). Topos keeps its current small online-adapting
   `LatentForwardModel`; Phantasia stays DreamerV3. If a predictor checkpoint ever
   appears, reopen only as a **frozen prior + online residual**, never as a
   Phantasia replacement. **DECIDED / CLOSED.**
