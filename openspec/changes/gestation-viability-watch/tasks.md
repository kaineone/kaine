## 1. Verdict (kaine/cycle/gestation.py)
- [ ] 1.1 Per-withdrawal history (lived time, conclusive?, pull, single pass, replicated) and the R0-R3 verdict after each withdrawal; config keys with the validated defaults and `viability_watch` (default true).
- [ ] 1.2 Publish `gestation.viability` once and write `state/lifecycle/gestation_viability.json` atomically.

## 2. Runner (kaine/research/ignition_study/runner.py)
- [ ] 2.1 Poll the viability file in the gestation step loop; on unviable: SIGTERM the child (no preservation request), wait for exit, record `failed:gestation_unviable` with the evidence, write `ENDED-NOTE.md`, halt.

## 3. Tests
- [ ] 3.1 Verdict: R0-R3 each fire on synthetic histories built from the validation patterns; a slow learner (80 bpm pattern) is never flagged; watch off disables it.
- [ ] 3.2 Runner: a fake child plus a viability file leads to SIGTERM, the failed record, the note and the halt, with no preservation request and no deletion.

## 4. Docs
- [ ] 4.1 Gestation chapter (the watcher, its rules and evidence); study chapter (the outcome and the note); configuration appendix.
