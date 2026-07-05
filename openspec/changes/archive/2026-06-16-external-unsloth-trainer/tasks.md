# Tasks (design-first proposal — implement on approval)

## 1. External trainer subprocess
- [x] 1.1 Standalone external entry script (run by the configured trainer python; imports only unsloth/trl/peft/datasets, NEVER `kaine`): reads `job.json` + `pairs.jsonl`, runs the real unsloth DPO, writes the adapter + `result.json`.
- [x] 1.2 Kaine-side `SubprocessVoiceTrainer` (runtime venv): writes the job spec, invokes `trainer_python` with explicit argv (no shell), timeout, CWD = job dir; validates exit code + `result.json.ok` + non-empty adapter dir; returns a `TrainOutcome` matching the in-process trainer. Fail loud on any miss — never a fake success.

## 2. Selection + config
- [x] 2.1 `[hypnos.voice_alignment]`: `trainer_backend` (in_process|subprocess, default in_process), `trainer_python` (path), `trainer_workdir`. Ship defaults so the in-process path is unchanged.
- [x] 2.2 `boot.py::make_hypnos` selects the trainer by backend. `subprocess` backend with empty/invalid `trainer_python` → clear config error at boot (mirror the existing missing-`[training]`-extra guard); never silently degrade.

## 3. Gates unchanged
- [x] 3.1 Confirm the returned adapter flows through the existing capability gate, abliteration gate, and adapter merge exactly as the in-process path (no change to those).

## 4. Boundary + tests
- [x] 4.1 Verify the external entry script is NOT in the `kaine` import graph (import-linter contracts still green; the script is invoked by path, not imported).
- [x] 4.2 Tests: job-spec round-trip (serialize → a FAKE/stub external entry that echoes a tiny adapter → readback); fail-loud on non-zero exit / missing adapter / empty `result.json`; config-error on subprocess-without-python; backend selection in `make_hypnos`. Heavy real-unsloth DPO is NOT run in CI (no GPU/extra) — covered by a stub entry; a real end-to-end smoke is a documented manual step.
- [x] 4.3 Docs: present-tense — `docs/processes/voice-alignment.md` (or sleep-maintenance) gains the out-of-process trainer + the external-env requirement (and the AMD unsloth-core note); how to point `trainer_python` at Unsloth Studio.

## 5. Validate
- [x] 5.1 Full suite green; import-linter green; `openspec validate external-unsloth-trainer --strict`.
