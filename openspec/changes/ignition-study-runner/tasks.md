## 1. Implementation

- [x] 1.1 `kaine/research/ignition_study/plan.py`: the plan, its validation, `init` (layout, symlinks, refusal on an existing study).
- [x] 1.2 `overlay.py`: the per-line, per-step operator overlay (deep merge, absolute model directories, module set).
- [x] 1.3 `runner.py`: process control (start, gestation birth detection and preserve, viewing completion, timeouts through preserve-and-stop, results), `steps.jsonl`, resume, `--retry-failed`, lock.
- [x] 1.4 `__main__.py`: `init`, `run`, `status`.
- [x] 1.5 `docs/operations.md`: running the module-ignition study.

## 2. Verification

- [x] 2.1 Unit tests: plan validation; the overlay (exact module set, isolation keys, operator values kept, no secrets); resume from a partial `steps.jsonl`; a failed step halts; a double `init` refuses; the lock.
- [x] 2.2 A dry run end to end with a stand-in cycle script (no entity): gestation → birth → P0, then two viewings per line, with the step records checked; a stand-in that exits 7, one that reports `ok: false`, and one that times out each halt the study with the right outcome.
- [ ] 2.3 Offline suite green; `openspec validate ignition-study-runner --strict`.
