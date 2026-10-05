## Why

The offline novelty replay (`novelty-content-fingerprint`, Phase 1) ran the real perception modules on a CPU-only process and a throwaway data root. That exposed three defects.

- **Topos loads its encoder in fp16 even on CPU, and that breaks emotion2vec.**
  - Half precision on CPU makes one 16-frame clip take minutes.
  - Loading with `torch_dtype=float16` switches the process-wide default dtype while the load runs, so emotion2vec, loading in another thread at the same time, builds its model in fp16.
  - Every later inference then fails with "expected scalar type Float but found Half", and the classifier silently returns neutral. A CPU-only process running both modules gets no vocal-emotion reading.
- **Topos ignores the data root and `KAINE_MODELS_DIR` for its weights.** The InternVideo-Next loader resolves the weights directory at call time, but `InternVideoNextEncoder` passes in the import-time constant `DEFAULT_WEIGHTS_DIR`. That constant freezes `state/models` relative to the working directory when the module is first imported. The setup fetch defaults to the same constant.
- **A misleading device log.** When a requested CUDA device does not exist, `kaine.hardware` logs "falling back to cuda:0" even when it actually returns `cpu`, because the log names the configured fallback, not the resolved device.

## What Changes

- Topos loads its encoder in fp16 only on CUDA, and in float32 elsewhere.
- emotion2vec loads with `fp16=False` on non-CUDA devices, and verifies after loading that its parameters are float32 on CPU. If they are not, it casts them, and logs once that it did. This defends against any other module changing the default dtype at load time.
- `InternVideoNextEncoder` passes `weights_dir=None` through unless one was configured, so the loader resolves the path at call time under the installed data root or `KAINE_MODELS_DIR`. The setup fetch resolves its default directory at call time too. `DEFAULT_WEIGHTS_DIR` stays as a constant for existing readers.
- The device-fallback warnings name the device actually returned.

## Impact

- CPU tiers get real vocal-emotion readings.
- The Topos weights follow the data root.
- Research impact: none for GPU hosts. CPU-only runs previously had no emotion signal.
