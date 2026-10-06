## Why

The offline novelty replay (`novelty-content-fingerprint`, Phase 1) ran the real perception modules on a CPU-only process and a throwaway data root. That exposed three defects.

- **Topos loads its encoder in fp16 even on CPU, and that breaks emotion2vec.**
  - Half precision on CPU makes one 16-frame clip take minutes.
  - Loading with `torch_dtype=float16` switches the process-wide default dtype while the load runs, so emotion2vec, loading in another thread at the same time, builds its model in fp16.
  - Every later inference then fails with "expected scalar type Float but found Half", and the classifier silently returns neutral. A CPU-only process running both modules gets no vocal-emotion reading.
- **Topos ignores the data root and `KAINE_MODELS_DIR` for its weights.** The InternVideo-Next loader resolves the weights directory at call time, but `InternVideoNextEncoder` passes in the import-time constant `DEFAULT_WEIGHTS_DIR`. That constant freezes `state/models` relative to the working directory when the module is first imported. The setup fetch defaults to the same constant.
- **A misleading device log.** When a requested CUDA device does not exist, `kaine.hardware` logs "falling back to cuda:0" even when it actually returns `cpu`, because the log names the configured fallback, not the resolved device.

## What Changes

- No perception loader passes `torch_dtype=` to `from_pretrained`. Topos loads InternVideo-Next in the default dtype and casts it afterwards: fp16 on CUDA and XPU, float32 elsewhere. Nothing changes the process-wide default dtype while another module is loading.
- On a non-CUDA device, emotion2vec casts every floating-point parameter and buffer to float32 after loading and verifies the result. If any tensor is still not float32, the load counts as failed and the classifier reports itself unavailable, rather than returning neutral by failure.
- `InternVideoNextEncoder` passes `weights_dir=None` through unless one was configured, so the loader resolves the path at call time. The setup fetch resolves its default directory at call time too. `DEFAULT_WEIGHTS_DIR` stays as a constant for existing readers.
- Model paths in config (`[topos].encoder_local_dir` and the two `sherpa_model_dir` keys) that start with `state/models` resolve under `$KAINE_MODELS_DIR` when it is set, with or without a data root, and otherwise under the data root as before.
- The device-fallback warnings name the device actually returned.

## Impact

- CPU tiers get real vocal-emotion readings.
- The Topos and speech-model weights follow `$KAINE_MODELS_DIR`, or the data root when it is unset.
- Research impact: any run with vocal emotion enabled could have recorded
  neutral-by-failure emotion on both CPU and GPU hosts, because the default
  dtype race happened whenever InternVideo-Next and emotion2vec loaded at the
  same time. The base-thesis studies are unaffected, because their overlay
  disables emotion2vec (`emotion_model_id = ""`).
