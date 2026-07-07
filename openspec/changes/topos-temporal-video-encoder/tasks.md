# Tasks — Topos temporally-native video encoder (InternVideo-Next)

Implementation is **phased**. **Phase 1 (this pass): foundation + loader only** —
vendoring, offline-weights fetch, provenance, the no-remote-code loader, and the
`encoder_backend` selector scaffolding. **Phase 2 (later pass): the real encoder**
— clip seam, ring buffer, cadence, pooling, salience re-tuning, and only then the
default flip to InternVideo-Next.

**No pretend processes (load-bearing sequencing).** InternVideo-Next MUST NOT
become the shipped default until its clip forward pass is genuinely implemented
(Phase 2). Through Phase 1 the shipped default stays `DINOv2Encoder` (a real,
working encoder); selecting `encoder_backend = "internvideo_next"` before Phase 2
raises a loud `NotImplementedError` (fail honestly) — it never returns a
fake/zero/simulated embedding. The default flip lives in Phase 2 (task 6.1),
after the real encoder exists.

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
- [ ] 1.5 Declare `einops` / `timm` / `flash_attn` / `easydict` (vendored-code
      deps) in an extra — **deferred to Phase 2** (the real forward pass), since
      Phase 1 never imports the modeling module (the stub encoder raises before
      load). Recorded here so it is not forgotten.

## 2. Clip-native encoder seam

- [x] 2.4 **PHASE 1 (DONE).** Add the `encoder_backend` selector: a real
      `make_encoder(backend, …)` factory in `kaine/modules/topos/encoder.py`
      returning `DINOv2Encoder` (`"dinov2"`) or the (Phase-2-stub)
      `InternVideoNextEncoder` (`"internvideo_next"`), wired through `Topos` +
      `make_topos` + config. **Phase-1 default = `"dinov2"`** (real encoder);
      selecting `"internvideo_next"` raises `NotImplementedError` until Phase 2.
- [ ] 2.1 **PHASE 2.** Extend the `Encoder` protocol: add `clip_len: int` and
      `async encode_clip(frames) -> list[float]`.
- [ ] 2.2 **PHASE 2.** Fill `InternVideoNextEncoder`: load the vendored classes
      via the Phase-1 loader (frozen `eval()` / `requires_grad_(False)`, fp16 on
      `[topos].device`), `clip_len = 16`; `encode_clip` runs `extract_features` and
      pools `[1, 4096, 768] → 768` (native attention-pool if reachable, else mean);
      probes `latent_dim = 768` at load.
- [ ] 2.3 **PHASE 2.** Adapt / retain `DINOv2Encoder` as `clip_len = 1`
      (`encode_clip` encodes `frames[-1]`).

## 3. Topos ring buffer + clip cadence

- [ ] 3.1 Add a RAM-only `deque(maxlen=clip_len)` frame ring buffer to `Topos`.
      `process_frame` appends; when full AND on the `clip_stride` boundary, call
      `encode_clip` and run the salience pipeline + publish; otherwise buffer and
      return without publishing.
- [ ] 3.2 No `topos.report` until the buffer first fills (warmup ≈ 1.6 s @ 10 Hz);
      document it.
- [ ] 3.3 Confirm EntityClock dilation carries through (stride counted in
      frame-ticks — no extra clock wiring).
- [ ] 3.4 Zero-persistence: add an explicit RAM-only note at the buffer site; keep
      the buffer out of `serialize()`.

## 4. Dim cascade 384 → 768

- [ ] 4.1 Verify `LatentForwardModel` input dim auto-derives to 768 via
      `encoder.latent_dim` (no code change expected); optionally bump
      `forward_model_units` per 0.4.
- [ ] 4.2 Guard `Topos.deserialize`: if a forward-model checkpoint's tensor shapes
      don't match the running `latent_dim`, discard the forward-model weights with
      a warning (the online model re-learns). Add a test.
- [ ] 4.3 Confirm-and-document that Phantasia `obs_dim` (19, workspace-derived) is
      UNAFFECTED — no Phantasia code/config/checkpoint change.

## 5. Salience re-tuning (calibration pass)

- [ ] 5.1 Run the new encoder over the seeded `reproducible-perception` feed at
      the shipped `clip_stride`, `forward_prediction` on; record change /
      habituation / normalized-prediction-error distributions.
- [ ] 5.2 Re-derive `change_alert_threshold` (~90th pct of observed change);
      re-verify `baseline_salience` / `alert_salience`. Commit derived values with
      the feed seed + window as provenance.

## 6. Config, docs, tests

- [ ] 6.1 **PHASE 2 (the default flip — after the real encoder exists).**
      `config/kaine.toml [topos]`: flip `encoder_backend` to `"internvideo_next"`,
      set `encoder_model_id` (InternVideo-Next), `clip_len`, `clip_stride`,
      `clip_resolution = 224`, `pooling`, re-tuned thresholds; REMOVE
      `facebook/dinov2-small` as the default. Phase 1 already added the
      `encoder_backend` / `encoder_revision` / `encoder_local_dir` keys (default
      `"dinov2"`); this task only performs the flip once InternVideo-Next is real.
- [ ] 6.2 Update `docs/modules/topos.md` (768-dim temporally-native clip embedding,
      clip cadence, warmup, ring buffer, no-remote-code loading) and
      `docs/tech-choices.md` (replace the DINOv2 §Vision entry with InternVideo-Next:
      MIT, OpenGVLab, vendored+pinned, temporally-native).
- [ ] 6.3 Update the opt-in real-encoder test (`KAINE_TOPOS_RUN_REAL_ENCODER=1`) to
      assert a 768-dim pooled vector from a 16-frame clip. Fake-encoder unit tests
      stay dim-agnostic.
- [ ] 6.4 Add a test asserting no `trust_remote_code=True` and no runtime hub
      access on the encoder load path.

## 7. Verify

- [ ] 7.1 Full suite green (no entity boot).
- [ ] 7.2 Pre-boot dry-run: perception feed → new encoder → `topos.report` at the
      clip cadence, 768-d latent, re-tuned salience firing sanely on the seeded
      feed; loaded fully offline from vendored code + local weights.
