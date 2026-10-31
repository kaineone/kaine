## 1. Code (one pull request, before the study)

- [ ] 1.1 A checkpoint-verification helper beside `kaine/lifecycle/resume_checkpoint.py` (`read_checkpoint` with the configured encryptor; presence, decrypt, parse, identity, stage). Tests: `tests/test_resume_checkpoint_verify.py`.
- [ ] 1.2 The runner calls it after an unviable child exits; records `state_restartable` and the timestamp; on failure records `failed:development_unviable_state_incomplete` and raises `StudyCritical`. Tests: extend `tests/test_ignition_study_runner.py` and `tests/test_ignition_study_viability.py` (restartable; missing checkpoint halts critical; step directory unchanged).
- [ ] 1.3 A restart test on a real state tree: a short developmental cycle with the fake organ, SIGTERM through the runner's unviable path, then a plain start resumes with the same identity and progress (`tests/test_unviable_stop_restarts.py`).
- [ ] 1.4 `ENDED-NOTE.md` license section (design D3). Test: the note's text.
- [ ] 1.5 `docs/15-experiments/ignition-study.md`: what an unviable stop leaves and how to restart or decommission it.

## 2. Paper

- [ ] 2.1 Paper revision note for §6.5 and §7: an unviable developmental phase is stopped with its state kept and restartable, handled under CAL Art. 4.2.

## 3. Operator decision

- [ ] 3.1 Whether an unviable stop should also request a preservation bundle (reason `development_unviable`) before SIGTERM, which would reverse the 2026-10-03 no-bundle policy. If yes, a follow-up modifies the existing unviable-stop requirement.
- [ ] 3.2 `openspec validate unviable-phase-state-kept --strict`.
