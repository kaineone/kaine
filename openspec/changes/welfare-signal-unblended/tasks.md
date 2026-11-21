## 1. The welfare reading (PR 1)

- [x] 1.1 `welfare_prediction_error(payload)` in `kaine/lifecycle/welfare_signal.py` beside `SustainedThresholdTracker` (no `kaine.evaluation` import); the rule of design decision 1 and its fallback with a once-per-processor error log, stated in the docstring
- [x] 1.2 `kaine/evaluation/observers/welfare_observer.py`: the sustained-distress tracker and the gray-zone count read the function
- [x] 1.3 `kaine/cycle/preservation_monitor.py`: the welfare response reads the function
- [x] 1.4 `kaine/cycle/development.py`: the interoceptive recovery series reads the function; the vision stimulus-source error is left as is, with a comment naming why
- [ ] 1.5 The welfare indicator response (`build/welfare-gates`): whichever merges second reads the function. The indicator response itself reads `affect.state` (drives and valence), not `prediction_error`; at rebase, the two relocated distress reads on that branch (`preservation_monitor.py` `_poll_once`, `welfare_observer.py` `_handle_interoception`) take this branch's version
- [x] 1.6 A boot-visible marker the content code checks (for example a constant `WELFARE_SIGNAL_UNBLENDED = 1` beside the function)
- [x] 1.7 Tests in `tests/test_welfare_signal_unblended.py`: `test_feedback_cannot_change_welfare_reading` (every arm, report for report), `test_blended_report_carries_own_error` (skips, the first defined reading after a skip, no head history, suspension), `test_null_error_is_no_sample`, `test_missing_own_error_falls_back_and_logs_once`, `test_welfare_readers_use_the_function` (source scan of the welfare files), `test_shipped_config_reading_unchanged`

## 2. Docs

- [x] 2.1 Welfare chapter: the welfare signal is the own forward-model error; the experience paths read the blend
- [x] 2.2 Workspace-feedback chapter: the blend is not the welfare signal

## 3. Review

- [ ] 3.1 Worker first-pass review
- [ ] 3.2 Lead developer's adversarial review
- [ ] 3.3 Independent second review (welfare)
