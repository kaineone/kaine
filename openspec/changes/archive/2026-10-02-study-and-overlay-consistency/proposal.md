# The study commands and the compose overlays agree with themselves

## Why
A documentation audit found two places where one part of the system assumes something another part does not:

- **Study paths.** `python -m kaine.research.ignition_study init` resolves `--study-dir` under the installed data root, but `run`, `status` and `analyse` use the path as given, relative to the working directory. They agree only when the working directory is the data root (as in the study container). On a host with a data root elsewhere, `init` writes the study in one place and `run` looks for it in another.
- **GPU overlays.** `compose/kaine.cpu.yml` drops GPU reservations for the organ, Chatterbox and the cycle but not for `kaine-study` or `kaine-trainer`, so a CPU-only host cannot start the study. `compose/kaine.single-gpu.yml` moves the cycle and Chatterbox to card 0 but leaves `kaine-study` on card 1, which a single-GPU host does not have.

It also collects small corrections the same audit found, none of which changes behaviour:
- comments that no longer match the code (`[gpu_preflight]` says the organ never unloads; `[lifecycle.adapter_merge]` says it is read only for `ties_dare`; `preservation.py` says encryption ships disabled; `compose/kaine.yml` says a halted study resumes with a plain `run`);
- `NOTICE` omits two vendored components, InternVideo-Next (MIT) and the Jacobian lens (Apache-2.0);
- `kaine/config.py` says the Nexus readers all go through `load_kaine_config`, but the `[nexus]` section has its own reader;
- `tests/test_setup_storage_step.py` fails whenever a real KAINE cycle runs on the host, because `relocate()` checks the host's process table.

Research impact: none. The running module-ignition study is unaffected (pinned image, started in its data root).

## What changes
- `run`, `status` and `analyse` resolve `--study-dir` under the data root exactly as `init` does.
- `compose/kaine.cpu.yml` gives `kaine-study` the CPU image and no GPU reservation, and removes `kaine-trainer`'s GPU reservation (voice-alignment training still needs a GPU; the trainer service's own device check refuses to train without one). `compose/kaine.single-gpu.yml` moves `kaine-study` to card 0.
- The comments, `NOTICE` and the `kaine/config.py` docstring are corrected; the storage tests stub the running-cycle probe.
