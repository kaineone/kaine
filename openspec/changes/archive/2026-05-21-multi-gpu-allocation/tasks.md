## 1. Hardware layer

- [x] 1.1 `select_device` accepts `cuda:N`; raises on missing index
- [x] 1.2 `resolve_device(preferred, fallback)` — warning + fallback
- [x] 1.3 `available_cuda_devices()` enumeration
- [x] 1.4 `tune_cpu_threads()` — bounded torch thread count
- [x] 1.5 `describe_host()` adds `cuda_devices` field

## 2. Module wiring

- [x] 2.1 Topos encoder routes through `resolve_device`
- [x] 2.2 Mnemos embedder routes through `resolve_device` (plus `embedder_device_preference` plumbing in Mnemos.__init__ and boot factory)
- [x] 2.3 AudioInput forwards `emotion_device` explicitly
- [x] 2.4 Hypnos `VoiceAlignmentConfig.training_device` field

## 3. Boot wiring

- [x] 3.1 `build_registry` logs device assignment per module via `_log_device_assignments`
- [x] 3.2 Cycle entrypoint calls `tune_cpu_threads` before module init
- [x] 3.3 Factories thread the new config keys

## 4. Config defaults

- [x] 4.1 `[topos].device = "cuda:1"` (with fallback warning on single-GPU hosts)
- [x] 4.2 `[mnemos].device = "cpu"` (frees cuda:1 for Topos)
- [x] 4.3 `[hypnos.voice_alignment].training_device = "cuda:0"`
- [x] 4.4 `[audio_in].emotion_device = "cpu"` (explicit, per paper §3.1)

## 5. Tests

- [x] 5.1 `test_hardware_multi_gpu.py` (15 tests)
- [x] 5.2 `test_boot_device_logging.py` (1 test)
- [x] 5.3 `test_module_device_pinning.py` (6 tests)

## 6. Docs

- [x] 6.1 `SETUP.md` §1.4 marked decided with allocation table
- [x] 6.2 `DEPENDENCIES.md` GPU allocation table with CUDA_VISIBLE_DEVICES override guidance
- [ ] 6.3 `ARCHITECTURE.md` per-module device row (deferred — covered in DEPENDENCIES.md)

## 7. Verification

- [x] 7.1 Full suite passes (786 / 12 skipped)
- [x] 7.2 `openspec validate multi-gpu-allocation --strict` clean
- [x] 7.3 `describe_host()` now returns `cuda_devices` list
- [ ] 7.4 Commit, merge, archive, tag v1.3-multi-gpu
