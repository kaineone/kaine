## 1. Out-of-process merge

- [ ] 1.1 Add `kaine/lifecycle/adapter_merge_worker.py`. It reads a private job file, runs the existing PEFT merge and checks, and writes a result file atomically (0600).
- [ ] 1.2 `TiesDareAdapterMerger.merge` runs the worker as a child process. It uses an allowlisted environment with Hugging Face offline, a timeout, and a fail-closed reading of the result.
- [ ] 1.3 Tests:
  - no `transformers` or `peft` import in the parent;
  - the default dtype stays float32;
  - a crash, a timeout or a garbage result refuses the merge;
  - a real tiny-adapter merge runs where peft is installed.
