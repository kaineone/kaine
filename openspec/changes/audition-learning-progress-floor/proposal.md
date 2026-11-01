## Why

The learning-progress floor `lp_0` (paper A.4, Table A1; `[affect].learning_progress_floor`, 0.20) is calibrated on vision noise: a frozen vision forward model, with the noise fitted to the tenth test boot, relieves about as rarely under max pooling as it did under mean pooling at 0.05. Audition uses the same value, both for the drives (curiosity's build, boredom's relief) and as the hearing-stage release threshold of `developmental-stimulus-progress`. That change's live-gap record (2026-11-01) left audition's floor as the next question: under live conditions the full-span reading rarely cleared 0.20 at the hearing steps that register.

Since then the hearing-stage reading bins awake reports only (`developmental-stimulus-progress` D5c). This change calibrates audition's floor on audition's own noise under live conditions, from the band-step harness, with no entity.

## What Changes

- **A per-source floor for audition.** `[affect].audition_learning_progress_floor`, in `[0, 1)`, floors audition's learning progress; every other source keeps `learning_progress_floor`. The pooled `lp+` becomes the largest per-source progress over its own floor, `max_s (lp_s - lp_0,s) / (1 - lp_0,s)`, which equals the old formula when the floors are equal. The hearing-stage owner uses audition's floor as its `lp_0`. Without the key nothing changes.
- **The calibrated value, 0.19.** The 95th percentile, rounded up, of a learning audition model's awake full-span readings in hearing stages 3 and 4 (nothing left to learn) under live conditions (arousal, developmental rests, broadcast context), settled schedule, three seeds, with and without the added sounds. A frozen model (no adaptation) gives 0.03, reported as a lower bound and not used.
- **Record and rerun.** The calibration record (`docs/records/validation/audition-lp-floor/2026-11-01-calibration.json`) and the live gap rerun with the calibrated floor.

## Capabilities

### New Capabilities

### Modified Capabilities

- `affect`: per-source learning-progress floors; audition's floor.
- `developmental-stimulus`: the hearing-stage owner's floor is audition's.

## Impact

- Code: `kaine/modules/affect/module.py` (`_lp_floors`, `learning_progress_floor_for`, `_progress`), `kaine/boot/factories/affect.py`, `kaine/boot/perception_feed.py` (the stage owner's floor), `kaine/boot/stimulus_version.py`, `config/kaine.toml`.
- Tools: `tools/research/band_step_check.py --frozen-audition`, `tools/research/audition_lp_floor_calibration.py`.
- Not changed: `InterestGoalScorer` (the interest goal factor, not shipped) keeps the shared floor for every module.
- Welfare: a lower audition floor gives audition's progress slightly more weight in boredom's relief and curiosity's build; the change is 0.01 and its effect on boredom's deprivation share is reported with the live gap rerun. No welfare bar, threshold or reset changes.
