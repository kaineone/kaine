## Why

The offline novelty replay (`novelty-content-fingerprint`, Phase 1) ran the real perception modules on a CPU-only process and a throwaway data root. That exposed three defects.

- **emotion2vec fails on every CPU-only host.** funasr loads the checkpoint in fp16 when its config asks for it, even when the device is the CPU. Every inference then fails with "expected scalar type Float but found Half", and the classifier silently returns neutral. CPU tiers never get a vocal-emotion reading.
- **Topos ignores the data root and `KAINE_MODELS_DIR` for its weights.** The InternVideo-Next loader resolves the weights directory at call time, but `InternVideoNextEncoder` passes in the import-time constant `DEFAULT_WEIGHTS_DIR`. That constant freezes `state/models` relative to the working directory when the module is first imported. The setup fetch defaults to the same constant.
- **A misleading device log.** When a requested CUDA device does not exist, `kaine.hardware` logs "falling back to cuda:0" even when it actually returns `cpu`, because the log names the configured fallback, not the resolved device.

## What Changes

- emotion2vec loads with `fp16=False` on non-CUDA devices, and verifies after loading that its parameters are float32 on CPU. If they are not, it casts them, and logs once that it did.
- `InternVideoNextEncoder` passes `weights_dir=None` through unless one was configured, so the loader resolves the path at call time under the installed data root or `KAINE_MODELS_DIR`. The setup fetch resolves its default directory at call time too. `DEFAULT_WEIGHTS_DIR` stays as a constant for existing readers.
- The device-fallback warnings name the device actually returned.

## Impact

- CPU tiers get real vocal-emotion readings.
- The Topos weights follow the data root.
- Research impact: none for GPU hosts. CPU-only runs previously had no emotion signal.
