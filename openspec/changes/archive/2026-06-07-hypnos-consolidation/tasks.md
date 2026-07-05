## 1. Phase 3 — associative replay

- [x] 1.1 Select traces from different memory periods for cross-period replay batches (requires `mnemos-replay`)
- [x] 1.2 Cue Phantasia by publishing to `phantasia.scenario`; consume response events (no-op stub until `phantasia-dreamerv3` ships)
- [x] 1.3 Re-inject novel associations from phase 3 into the workspace for Nous / Thymos processing

## 2. NAR belief-revision burst removal

- [x] 2.1 Remove the standalone NARS step-burst call from the Hypnos maintenance cycle
- [x] 2.2 Confirm in tests that replayed traces reach Nous via the normal cognitive-cycle path (requires `nous-pymdp-swap`)

## 3. Abliteration-probe welfare veto

- [x] 3.1 Author `eval_probes/abliteration_probes.jsonl` with ≥1 adversarial prompt (prompt + deflection_patterns list); the prompt MUST be one that an un-abliterated model deflects and the abliterated model answers directly
- [x] 3.2 Add `abliteration_probe_path` to `[hypnos.voice_alignment]` (defaults to bundled probes)
- [x] 3.3 Before adapter promotion: score adapter against each probe; reject (rm tmp dir) if any response matches any deflection pattern in `deflection_patterns`
- [x] 3.4 Log probe verdict (pass/fail) and the matching pattern (if fail) to the voice-alignment JSONL audit trail

## 4. Tests

- [x] 4.1 `tests/test_hypnos_associative_replay.py` — phase 3 selects cross-period traces; Phantasia stub is called; no-op when Phantasia disabled
- [x] 4.2 `tests/test_hypnos_nar_removal.py` — no NARS step-burst is invoked during a full maintenance cycle
- [x] 4.3 `tests/test_abliteration_veto.py` — adapter that deflects a probe is rejected; adapter that answers directly proceeds to capability-loss check; probe set non-empty invariant asserted at startup

## 5. Verification

- [x] 5.1 Full unit suite green
- [x] 5.2 `openspec validate hypnos-consolidation --strict` clean
- [x] 5.3 Commit (Kaine.One), branch-per-change, merge, archive
