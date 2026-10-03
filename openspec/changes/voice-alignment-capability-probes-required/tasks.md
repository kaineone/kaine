## 1. Behaviour
- [x] 1.1 `kaine/boot.py`: `_require_non_empty_capability_probes(voice_config)` beside `_require_non_empty_abliteration_probes`, called on every backend path that calls the abliteration check.
- [x] 1.2 `kaine/modules/hypnos/unsloth_trainer.py`: default evaluator with `require_probes=True`; an `EmptyCapabilityProbeSetError` rejects the adapter with the reason.
- [x] 1.3 `scripts/hypnos_external_train.py`: no usable capability probe → reject with reason "capability probe set is empty".

## 2. Tests
- [x] 2.1 Boot refuses on each backend with an empty and with a missing capability probe file.
- [x] 2.2 In-process trainer and external script reject on an empty set; the gate-parity test covers both.

## 3. Docs
- [x] 3.1 Sleep chapter (voice alignment) and the `[hypnos.voice_alignment].capability_probe_path` row.
