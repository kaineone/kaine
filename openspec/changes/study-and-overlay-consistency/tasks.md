## 1. Behaviour
- [x] 1.1 `kaine/research/ignition_study/__main__.py`: `run`, `status` and `analyse` resolve `--study-dir` with `kaine.storage.resolve`, as `init` does.
- [x] 1.2 `compose/kaine.cpu.yml`: `kaine-study` gets `image: ${KAINE_IMAGE:-kaine:cpu}`, `build.args.FLAVOR: cpu` and no GPU reservation; `kaine-trainer` gets no GPU reservation.
- [x] 1.3 `compose/kaine.single-gpu.yml`: `kaine-study` reserves card 0.

## 2. Corrections
- [x] 2.1 `config/kaine.toml` `[gpu_preflight]` and `[lifecycle.adapter_merge]` comments.
- [x] 2.2 `kaine/lifecycle/preservation.py` encryption comment; `compose/kaine.yml` study resume comment.
- [x] 2.3 `NOTICE`: InternVideo-Next and jlens entries.
- [x] 2.4 `kaine/config.py` docstring: the `[nexus]` section's own reader.
- [x] 2.5 `tests/test_setup_storage_step.py`: autouse fixture stubbing `cycle_process_running` to False.

## 3. Tests
- [x] 3.1 With a data root installed and a different working directory, `status` finds a study that `init` created.
- [x] 3.2 Rendering the stack with the CPU overlay shows no GPU reservation on `kaine-study` and `kaine-trainer`; the single-GPU overlay shows card 0 for `kaine-study` (a test that parses the YAML files and merges the overlay over the base).
- [x] 3.3 The storage tests pass while a `kaine.cycle` process runs on the host.
