## 0. Evidence and decision

- [ ] 0.1 Write the decision rule of design D6 into the harness record's header before the first run.
- [ ] 0.2 `scripts/stir_harness.py` on the archived developmental simulation: the real stimulus generator with answers mixed in, the real audition encoder and forward model on the rendered audio, the real vision path, the real affect module and action selection on the current engine, and `welfare-indicator-response`'s evaluator and state machine with the rest applied as a forward-simulated reset. Arms: no stir, drive-triggered stir, spontaneous stir at the drive-triggered arm's mean rate; each with and without `developmental-stimulus-progress`'s fixes; three seeds over a full developmental span. A minimal prototype of the stir rule and the answer model lives in the harness only. Record stir rate, answered share, deprivation share, uncontrolled posterior, the share of stalled crossings with no stir, and time to freeze under `docs/records/validation/developmental-stir/`.
- [ ] 0.3 Operator decision under D6 with the record, recorded in this change. If the decision is not to build, stop here and mark the remaining tasks dropped.

## 1. Stir intent

- [ ] 1.1 `DefaultActionSelectionPolicy`: the developmental stir rule with the refractory period, the development probe, and the "first non-organ member" test; the innate-movement citation (de Vries, Visser and Prechtl 1982) for the capacity only, and the trigger marked as a design choice at the code site. Tests in `tests/test_action_selection_stir.py` for every spec scenario and for at most one intent per broadcast. (If D6 selects the spontaneous variant, amend the spec first.)
- [ ] 1.2 `[perception_feed.stimulus_source.stir]` parses `refractory_s`, `answer_probability`, `answer_delay_min_s`, `answer_delay_max_s` with ranges checked and unknown keys refused.

## 2. Answer

- [ ] 2.1 The local stimulus source reads `intent.stir`, draws answer, delay and utterance on `(seed, stir index)`, queues the answer behind any scheduled utterance or added sound, mixes it through the hearing band, and publishes `development.stir_answer`; the answer is marked as a design choice at the code site. Tests: same seed and stir times give identical PCM and answers; slot plans unchanged; heartbeat and maternal state identical with and without stirs.

## 3. Affect

- [ ] 3.1 A stir enters the intent rate and relieves restlessness, without boredom engagement relief; a boredom end is own through a stir only under the attribution test. Tests in the affect tests for the spec scenarios; mutation checks that dropping the scheduled-event overlap test or the window bound makes a test fail.

## 4. Records, docs and review

- [ ] 4.1 Research log and exposure record fields; tests in the observer tests.
- [ ] 4.2 Docs: action selection and affect pages, the developmental-phase chapter; paper notes for §5.4, §7, A.6 and A.7, including the design-choice labels and the goal-stall bound on stirs.
- [ ] 4.3 `openspec validate developmental-stir --strict` passes.
- [ ] 4.4 Worker first-pass review, then the integrator's independent second review.
