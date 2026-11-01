## Context

- `lp_0` (paper A.4) is the noise floor of the learning-progress measure: progress below it is treated as zero. The shipped 0.20 comes from a frozen vision model under the fitted test-boot vision noise.
- The hearing-stage owner (`developmental-stimulus-progress`) releases a stage when audition's full-span reading, on awake bins, stays below `lp_0` for 600 awake seconds. A floor below audition's noise would keep a stage with nothing to learn from ever saturating, so it would close only at the 7-hour cap; a floor above the progress of a stage that registers would close it as if there were nothing to learn.
- The band-step harness (`tools/research/band_step_check.py --live`) runs the real stimulus, audition, affect and workspace with the affect module's arousal, the developmental rests and broadcast context. Hearing stages 3 and 4 are the ones with nothing to learn (band-step record 2026-10-31: the new band carries 0.2 to 7% of the power and the error does not rise).

## Decisions

### D1. Calibrate on a learning model where there is nothing to learn

The null is the learning audition model's awake full-span readings in stages 3 and 4 of settled live runs (5 awake hours a stage, seeds 1 to 3, with and without the added sounds). These readings carry the noise the floor has to reject: the forward model keeps re-adapting to the maternal voice's episodes and the added sounds, which reads as progress without new structure (the maternal-voice calibration found the same). The floor is the 95th percentile of the null stage with the larger one, rounded up to 0.01: 0.19 (stage 3: p95 0.190; stage 4: 0.184).

Alternatives considered:
- **A frozen audition model** (`--frozen-audition`, never adapts), as the vision floor was set: p95 0.03. Without re-adaptation the readings are far smaller, and at 0.03 stages 3 and 4 read above the floor in 43% of awake readings, so they would close at the cap. Reported as a lower bound.
- **Keep the shared 0.20**: stages 0 to 2 read at or above it in 50% of awake readings and stages 3 and 4 in 3%. Close to the calibrated value; the calibration confirms the order of magnitude and sets audition's floor from its own data.

### D2. Per-source floors in the pooled progress

`lp+ = max_s max(0, lp_s - lp_0,s) / (1 - lp_0,s)`. With equal floors this is the old `max(0, max_s lp_s - lp_0) / (1 - lp_0)`, so a configuration without the key is unchanged byte for byte. Audition's floor applies wherever the affect module floors audition's progress and in the hearing-stage owner. The interest goal factor (`InterestGoalScorer`), not shipped, keeps the shared floor.

### D3. What this change does not touch

Welfare bars, thresholds, rests and resets, vision's floor and the learning-progress span and bins.

## Results

- Calibration record: `docs/records/validation/audition-lp-floor/2026-11-01-calibration.json`. At 0.19, stages 0 to 2 read at or above the floor in 56% of awake readings and stages 3 and 4 in 4.5%.
- The live gap rerun with the calibrated floor: see tasks 2.2 and the developmental-stimulus-progress live-gap record.

## Risks

- One stimulus, three seeds, with vision and interoception absent from the calibration runs; the floor should be rechecked when the stimulus or audition's encoder changes, as the stimulus version (which carries the floor) makes the records go stale.
