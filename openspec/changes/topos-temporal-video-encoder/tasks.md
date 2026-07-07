# Tasks — Topos temporally-native video encoder (InternVideo-Next)

Design-first change. These tasks are for the LATER implementation pass, after the
lead approves this design and the operator resolves the flags. Nothing here is
executed by authoring this change.

## 0. Operator decisions (blockers — resolve before implementation)

- [ ] 0.1 Decide DINOv2: delete `DINOv2Encoder`, or keep as non-default fallback
      behind `encoder_backend` (recommendation: keep). (design.md §6, Flag 1)
- [ ] 0.2 Confirm `clip_stride` default pending the shakedown GPU benchmark
      (recommendation: 3 ≈ 3.33 Hz). (Flag 2)
- [ ] 0.3 Confirm pooling: prefer native attention-pool if reachable, else mean;
      no L2-normalization (recommendation). (Flags 3, §2)
- [ ] 0.4 Confirm `forward_model_units` 128→256. (Flag 4)
- [ ] 0.5 Note the predictor option is closed (no predictor in the checkpoint);
      keep the current online head. (Flag 5, §8)

## 1. Vendor the model (security / provenance — do first)

- [ ] 1.1 Pin the exact HF commit SHA for
      `revliter/internvideo_next_base_p14_res224_f16`; record it as
      `encoder_revision`.
- [ ] 1.2 Vendor `modeling_internvideo_next.py`, `modeling_config.py`,
      `config.json`, `preprocessor_config.json` into `external/internvideo_next/`
      at that SHA.
- [ ] 1.3 Write `external/internvideo_next/UPSTREAM` (repo, pinned SHA, MIT text,
      vendoring-path decision) per the `external/dreamerv3/UPSTREAM` convention;
      add `SPDX-License-Identifier: MIT` headers + attribution.
- [ ] 1.4 Add a setup-time weight fetch (pinned SHA → git-ignored local models
      dir); set `HF_HUB_DISABLE_TELEMETRY=1`; document it. Verify NO runtime hub
      access and `trust_remote_code=False` at load.
- [ ] 1.5 Declare `einops` (or any vendored-code dep) in the vision extra if the
      modeling code needs it; otherwise no new dep.

## 2. Clip-native encoder seam

- [ ] 2.1 Extend the `Encoder` protocol: add `clip_len: int` and
      `async encode_clip(frames) -> list[float]`.
- [ ] 2.2 Implement `InternVideoNextEncoder`: loads the vendored classes from the
      local dir, frozen (`eval()`, `requires_grad_(False)`), fp16 on `[topos].device`,
      `clip_len = 16`; `encode_clip` runs `extract_features` and pools
      `[1, 4096, 768] → 768` (native attention-pool if reachable, else mean);
      probes `latent_dim = 768` at load.
- [ ] 2.3 Adapt / retain `DINOv2Encoder` as `clip_len = 1` (`encode_clip` encodes
      `frames[-1]`) if kept (per 0.1).
- [ ] 2.4 Add `encoder_backend` selection in `make_topos` / config wiring
      (`"internvideo_next"` default, `"dinov2"` optional).

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

- [ ] 6.1 `config/kaine.toml [topos]`: set `encoder_backend`, `encoder_model_id`
      (InternVideo-Next), `encoder_revision`, `encoder_local_dir`, `clip_len`,
      `clip_stride`, `clip_resolution = 224`, `pooling`, re-tuned thresholds;
      REMOVE `facebook/dinov2-small` as the default.
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
