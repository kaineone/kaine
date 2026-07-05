## 1. Forward model

- [x] 1.1 `kaine/modules/topos/forward.py` — `LatentForwardModel` predicting next DINOv2 latent from current + recurrent state (CPU); online step per frame; non-finite guard
- [x] 1.2 Bounded recurrent visual buffer (deque of recent latents) feeding temporal context

## 2. Salience

- [x] 2.1 Drive event salience from prediction error `||z(t) − ẑ(t−1)||`; keep `change_score`/`habituation_score` on the payload for diagnostics

## 3. Module + config

- [x] 3.1 Wire forward model + buffer into `Topos`; ensure DINOv2 encoder stays frozen (no grad)
- [x] 3.2 `serialize()`/`deserialize()` persist forward-model weights + buffer summary as a statistical descriptor (mean/variance of latent features) — no raw latent tensors
- [x] 3.3 `[topos]` config: `forward_model_units`, `prediction_error_window`, `visual_buffer_size`; update `make_topos` allowed keys

## 4. Tests

- [x] 4.1 `tests/test_topos_forward.py` — predictor shape; online step reduces error on a repeating latent sequence; non-finite guard
- [x] 4.2 `tests/test_topos_module.py` — salience tracks prediction error (predictable motion → low salience; novel frame → high); payload retains change/habituation; serialize roundtrip; assert serialized buffer dict has no raw tensor values (only numeric statistical summaries)

## 5. Verification

- [x] 5.1 Full unit suite green
- [x] 5.2 `openspec validate topos-forward-model --strict` clean
- [x] 5.3 Commit (Kaine.One), branch-per-change, merge, archive
