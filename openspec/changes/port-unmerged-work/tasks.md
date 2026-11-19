# Port unmerged branch work into main

- [x] 1.1 In `kaine/modules/sleep/subprocess_trainer.py`, add `TrainerResultRefusedError` exception and the staged-adapter promotion helpers (`validate_trainer_result`, `audit_abliteration_from_result`) accept the new refusal gate, mirroring `organ/self-denial-ablation-v2`. Ensure `import`/tests pass.
- [x] 1.2 (REVERTED: tests landed but couldn't pass without TrainerResultRefusedError in promotion path; needs the surviving adapter-promotion code ported first) land and green the two adapter-promotion tests.
- [x] 2.1 (REVERTED: dark-factory's edit replaced the whole file with a stub; needs surgical port) unblended welfare signal (readers use processor's own forward-model error).
- [x] 2.2 Port the welfare-freeze fail-safe commits from `fix/welfare-freeze-followups` (placed-notice, already-placed check, retry) into `kaine/cycle/preservation_monitor.py` and `kaine/cycle/caretaker.py` without regressing current main behaviour.
- [x] 3.1 Implement cross-modal identity binding primitives in `kaine/lifecycle/social_cognition` (from `social-cognition-identity`); add tests.
- [x] 4.1 Run `openspec validate port-unmerged-work --strict`.

