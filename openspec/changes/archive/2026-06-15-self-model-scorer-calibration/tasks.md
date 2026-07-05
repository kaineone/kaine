## 1. Calibration test

- [x] 1.1 Add `tests/test_eidolon_scorer_calibration.py` with a fixture that
      plants an `affect_correlation/*.jsonl` with a known valence above
      `valence_high` (>0.2), a known arousal, and a hedge count into a temp eval
      logs dir
- [x] 1.2 Assert `_signals_snapshot()` derives the exact expected signal dict
      (e.g. `valence_high=1.0`, `valence_low=0.0`) from the planted records
- [x] 1.3 Assert `_score_claim` returns 1.0 for a claim whose mapped signal the
      plant supports (HIGH case) and 0.0 for a claim whose mapped signal the
      plant contradicts (LOW case)
- [x] 1.4 Plant a `proactive_audit-<today>.jsonl` with content and assert the
      curiosity-proxy claim scores 1.0
- [x] 1.5 Assert `run_once`'s `aggregate_accuracy` equals the mean of the scored
      (non-None) claims for a known multi-claim self-description

## 2. Spec

- [x] 2.1 Add `evaluation-observers` ADDED requirement: the self-model accuracy
      scorer SHALL be calibrated against known planted signals (high, low,
      aggregate scenarios)

## 3. Validate

- [x] 3.1 `openspec validate self-model-scorer-calibration --strict` passes
- [x] 3.2 Calibration test is green
