# Tasks — Topos temporally-native video encoder (InternVideo-Next)

Implementation was **phased**. **Phase 1 (done): foundation + loader** —
vendoring, offline-weights fetch, provenance, the no-remote-code loader, and the
`encoder_backend` selector scaffolding. **Phase 2 (done, this pass): the real
encoder** — clip seam, ring buffer, cadence, pooling, the dim-cascade guard, and
the default flip to InternVideo-Next.

**No pretend processes (load-bearing sequencing).** The default flipped to
InternVideo-Next only now that its clip forward pass is genuinely implemented (a
real VideoMAE-preprocessed 16-frame clip → frozen forward → native-attention or
mean pool → 768-d). It never returns a fake/zero/simulated embedding: where the
real 91M model cannot run (no CUDA / `[internvideo]` deps / fetched weights in
this environment), the code fails honestly (`FileNotFoundError` on missing
weights, revision-mismatch error, etc.), and the integration is validated with an
injected fake torch model/processor — the salience-re-tuning calibration (§5) and
the real forward-pass dry-run (7.2) remain DEFERRED to a GPU shakedown rather than
faked.

## 0. Operator decisions — DECIDED (locked by operator 2026-07-06)

- [x] 0.1 **DINOv2: KEEP** as a non-default, non-shipped fallback behind
      `encoder_backend` (`"dinov2"`). InternVideo-Next becomes the shipped default
      and `facebook/dinov2-small` is stripped from the shipped default config +
      docs — **but that flip happens in Phase 2** (task 6.1), once the encoder is
      real; Phase 1 keeps `dinov2` as the working default. (design.md §6, Flag 1)
- [x] 0.2 **`clip_stride = 3`** default (≈ 3.33 Hz), marked **provisional** pending
      the shakedown GPU benchmark on the secondary GPU. (Flag 2)
- [x] 0.3 **Do NOT L2-normalize** the pooled vector; re-tune thresholds instead.
      Prefer the native attention-pool if reachable, else mean. (Flags 3, §2)
- [x] 0.4 **`forward_model_units` 128 → 256.** (Flag 4)
- [x] 0.5 **Predictor NOT adopted / option CLOSED.** Verified: the published
      checkpoint is encoder-only (single `model.safetensors`, no predictor/decoder).
      Topos keeps its current online `LatentForwardModel`; Phantasia stays
      DreamerV3. (Flag 5, §8)

## 1. Vendor the model (security / provenance — do first) — PHASE 1 (DONE)

- [x] 1.1 Pin the exact HF commit SHA for
      `revliter/internvideo_next_base_p14_res224_f16`
      (`ff2659b9be360a6b1e94b1eb381778a960da6019`); recorded as
      `encoder_revision` / loader `PINNED_REVISION`.
- [x] 1.2 Vendor `modeling_internvideo_next.py`, `modeling_config.py`,
      `config.json`, `preprocessor_config.json` into `external/internvideo_next/`
      at that SHA (verbatim upstream source — path (a), literal vendor).
- [x] 1.3 Write `external/internvideo_next/UPSTREAM` (repo, pinned SHA, MIT text,
      vendoring-path decision) per the `external/dreamerv3/UPSTREAM` convention;
      SPDX/attribution recorded in `UPSTREAM` + `__init__.py` (upstream source
      files kept byte-identical for a clean provenance diff — no injected headers).
- [x] 1.4 Add a setup-time weight fetch (`kaine/setup/internvideo_next.py`,
      pinned SHA → git-ignored `state/models/…` dir); sets
      `HF_HUB_DISABLE_TELEMETRY=1`. Loader (`internvideo_next_loader.py`) verified
      to pass `trust_remote_code=False` + `local_files_only=True` and to import the
      vendored classes directly — NO runtime hub access, NO remote code.
- [x] 1.5 Declare `einops` / `timm` / `flash_attn` / `easydict` (vendored-code
      deps) in a new `[internvideo]` extra (`pyproject.toml`) — the vendored
      modeling code hard-imports flash_attn/einops at forward time, so this extra
      targets a CUDA host; the DINOv2 fallback needs none of it.

## 2. Clip-native encoder seam

- [x] 2.4 **PHASE 1 (DONE).** Add the `encoder_backend` selector: a real
      `make_encoder(backend, …)` factory in `kaine/modules/topos/encoder.py`
      returning `DINOv2Encoder` (`"dinov2"`) or the (Phase-2-stub)
      `InternVideoNextEncoder` (`"internvideo_next"`), wired through `Topos` +
      `make_topos` + config. **Phase-1 default = `"dinov2"`** (real encoder);
      selecting `"internvideo_next"` raises `NotImplementedError` until Phase 2.
- [x] 2.1 Extended the `Encoder` protocol: added `clip_len: int` and
      `async encode_clip(frames) -> list[float]` (docstring bodies, not bare
      `...`, for CodeQL); kept per-frame `encode` for the foveation path.
- [x] 2.2 Filled `InternVideoNextEncoder`: loads the vendored classes via the
      no-remote-code loader (frozen `eval()` / `requires_grad_(False)`, fp16 on
      `[topos].device`), `clip_len = 16`; `encode_clip` builds a VideoMAE
      `pixel_values` clip and pools `[1, 4096, 768] → 768` via the **native
      attention-pool** head (`model(pixel_values)` → `clip_projector`; verified
      reachable by inspection) with a `pooling = "mean"` alternative; probes
      `latent_dim = 768` at load. Real load requires a CUDA host + `[internvideo]`
      deps + fetched weights (unavailable in CI); validated by fake model/processor
      injection (`load(_model=..., _processor=...)`).
- [x] 2.3 `DINOv2Encoder` retained as `clip_len = 1` (`encode_clip` encodes
      `frames[-1]`).

## 3. Topos ring buffer + clip cadence

- [x] 3.1 Added a RAM-only `deque(maxlen=clip_len)` frame ring buffer to `Topos`.
      `process_frame` appends; when full AND on the `clip_stride` boundary, calls
      `encode_clip` and runs the salience pipeline + publishes; otherwise buffers
      and returns `""` without publishing.
- [x] 3.2 No `topos.report` until the buffer first fills (warmup ≈ 1.6 s @ 10 Hz);
      documented in topos.md + config; covered by
      `test_no_report_until_ring_buffer_fills`.
- [x] 3.3 EntityClock dilation carries through — the stride is counted in
      frame-ticks (which already dilate); no extra clock wiring added.
- [x] 3.4 Zero-persistence: explicit RAM-only note at the buffer site and in
      `serialize()`; the buffer is absent from `serialize()` output
      (`test_serialize_excludes_frame_ring_buffer`).

## 4. Dim cascade 384 → 768

- [x] 4.1 `LatentForwardModel` input dim auto-derives via `encoder.latent_dim`
      (→ 768 for InternVideo-Next) — no code change; `forward_model_units` bumped
      128 → 256 in config per 0.4.
- [x] 4.2 Guarded `Topos.deserialize` with `LatentForwardModel.matches_state_shape`:
      a checkpoint whose tensor shapes don't match the running `latent_dim` is
      discarded with a warning (re-learns online), not force-loaded. Test:
      `test_deserialize_discards_mismatched_forward_model`.
- [x] 4.3 Confirmed Phantasia `obs_dim` (19, workspace-derived — no Topos latent
      flows into it) is UNAFFECTED; no Phantasia code/config/checkpoint change.

## 5. Salience re-tuning (calibration pass)

- [x] 5.1 **DONE (GPU shakedown 2026-07-10, RTX 4070 SUPER).** Ran the real encoder
      over the seeded feed (seed 0, 900 frames) at the shipped `clip_stride = 3`,
      `forward_prediction` on; recorded change / habituation / normalized-prediction-
      error distributions. See `docs/shakedowns/internvideo-next-gpu-shakedown.md`.
      Key result: cosine `change_score` is heavily compressed on attention-pooled
      embeddings (routine ≤ 0.0004, genuine scene cuts only ~0.008–0.043); the
      informative surprise signal is the forward-model prediction error (fired at the
      2.0× factor).
- [x] 5.2 **DONE.** Re-derived `change_alert_threshold` → **0.005** (was 0.5, which
      was unreachable — ~12× above even a total content change). Anchored between the
      measured routine floor (≤ 0.0004) and the encoder's measured scene-cut scale
      (≥ 0.008), since the smooth seeded feed has no genuine cuts to take a naive 90th
      percentile of. `baseline_salience` (0.2) / `alert_salience` (0.7) re-verified,
      unchanged. Set in `config/kaine.toml [topos]` + the `Topos` fallback default.

## 6. Config, docs, tests

- [x] 6.1 `config/kaine.toml [topos]`: flipped `encoder_backend` to
      `"internvideo_next"`, `encoder_model_id` to the InternVideo-Next id, added
      `clip_len = 16` / `clip_stride = 3` / `clip_resolution = 224` /
      `pooling = "attention"`; REMOVED `facebook/dinov2-small` as the default (now
      the documented fallback). Also flipped the code constant
      `DEFAULT_ENCODER_BACKEND` and threaded the new keys through `boot.make_topos`.
      `change_alert_threshold` left at the provisional 0.5 (see 5.2 — not re-tuned,
      honestly flagged rather than faked).
- [x] 6.2 Updated `docs/modules/topos.md` (768-dim temporally-native clip
      embedding, clip cadence, warmup, ring buffer, no-remote-code loading,
      backend selector) and `docs/tech-choices.md` (replaced the DINOv2 §Vision
      entry with InternVideo-Next: MIT, OpenGVLab, vendored+pinned, temporally
      native, off-Meta). Also refreshed configuration/licenses/architecture/
      glossary/security-and-privacy where they named DINOv2 as the default.
- [x] 6.3 Added the opt-in real-encoder test
      (`test_real_internvideo_next_produces_768_from_16_frame_clip`,
      `KAINE_TOPOS_RUN_REAL_ENCODER=1` + weights present) asserting a 768-dim
      pooled vector from a 16-frame clip. Fake-encoder unit tests stay dim-agnostic.
- [x] 6.4 Added `test_encoder_load_uses_offline_loader_not_automodel` (the encoder
      load path goes through the no-remote-code loader, not `AutoModel`, with the
      pinned revision + `HF_HUB_OFFLINE=1`), alongside the existing loader tests
      asserting `trust_remote_code=False` + `local_files_only=True`.

## 7. Verify

- [x] 7.1 Full suite green (no entity boot; vision tests use fake encoders).
- [x] 7.2 **DONE (GPU shakedown 2026-07-10).** Pre-boot dry-run: seeded feed → real
      encoder → `topos.report` at the clip cadence produced 768-d latents (all
      finite), salience firing sanely (baseline on routine, alert on the surprise via
      the prediction-error path); loaded fully offline from vendored code + local
      weights (config from the vendored dir, weights from the fetch dir), 91.0M params
      with zero missing/unexpected keys. Real forward pass: ~78 ms/clip median,
      ~1.06 GB peak VRAM, run WITHOUT flash_attn via the model's own eager attention
      path (no prebuilt wheel for torch 2.11/cu128). See
      `docs/shakedowns/internvideo-next-gpu-shakedown.md`.
