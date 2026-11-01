## 1. Calibration (no entity)

- [x] 1.1 `band_step_check.py --frozen-audition` (a forward model that never adapts) and `audition_lp_floor_calibration.py`.
- [x] 1.2 Settled live runs, seeds 1 to 3, with and without the added sounds, awake bins; frozen runs, seeds 1 to 3. Record `docs/records/validation/audition-lp-floor/2026-11-01-calibration.json`: floor 0.19 (stage 3 p95 0.190, stage 4 0.184); frozen lower bound 0.03.

## 2. Code

- [x] 2.1 `[affect].audition_learning_progress_floor`, per-source floors in `lp+`, the stage owner's floor, the stimulus version. Tests in `tests/test_affect_audition_floor.py`.
- [ ] 2.2 Rerun the live gap with the calibrated floor; record the share of awake readings above the floor in stages 0 to 2 and the stage releases.

## 3. Review

- [x] 3.1 `openspec validate audition-learning-progress-floor --strict`.
- [ ] 3.2 Worker first-pass review, then the integrator's second review.
