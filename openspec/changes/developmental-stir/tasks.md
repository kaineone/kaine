## 0. Decision

- [ ] 0.1 Operator decision on ordering (design D6), taken after `welfare-indicator-response` task 5.3 (offline indicator replay) and task 4 below. Record it in this change before any code task starts. If deferred past the study, stop here.

## 1. Stir intent

- [ ] 1.1 `DefaultActionSelectionPolicy`: the developmental stir rule with the refractory period, the development probe, and the "first non-organ member" test; the innate-movement citation (de Vries, Visser and Prechtl 1982) at the code site. Tests in `tests/test_action_selection_stir.py` for the three spec scenarios and for at most one intent per broadcast.
- [ ] 1.2 `[perception_feed.stimulus_source.stir]` parses `refractory_s`, `answer_probability`, `answer_delay_min_s`, `answer_delay_max_s` with ranges checked and unknown keys refused.

## 2. Answer

- [ ] 2.1 The local stimulus source reads `intent.stir`, draws answer, delay and utterance on `(seed, stir index)`, queues the answer behind any scheduled utterance, mixes it through the hearing band, and publishes `development.stir_answer`. Tests: same seed and stir times give identical PCM and answers; slot plans unchanged; heartbeat and maternal state identical with and without stirs.

## 3. Affect

- [ ] 3.1 A stir enters the intent rate and relieves restlessness, without boredom engagement relief; the answer window credits boredom ends as own. Tests in the affect tests for the spec scenarios; mutation check that removing the window makes a test fail.

## 4. Offline check (no entity boot)

- [ ] 4.1 Harness: the held-pool engine, the real affect module and action selection, fake perceptual reports at measured periods, and the answer model; report stir rate, answered share, boredom deprivation share and the uncontrolled posterior over simulated developmental spans, with and without the stir. Record under `docs/records/validation/developmental-stir/`.

## 5. Records, docs and review

- [ ] 5.1 Research log and exposure record fields; tests in the observer tests.
- [ ] 5.2 Docs: action selection and affect pages, the developmental-phase chapter; paper notes for §5.4, §7, A.6 and A.7.
- [ ] 5.3 `openspec validate developmental-stir --strict` passes.
- [ ] 5.4 Worker first-pass review, then the integrator's independent second review.
