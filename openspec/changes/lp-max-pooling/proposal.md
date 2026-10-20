## Why

In the tenth test boot vision ran out of material after about two hours, while audition still had progress of 0.06 to 0.24 per hour. The pooled learning progress was the mean over the processors, so it fell under the 0.05 floor and boredom built although one processor was still learning, while the interest rule was already sending attention to audition. Replaying the boot's logged per-processor values through the drive equation, the mean keeps boredom's steady state above threshold in most hours from h3 on, and the largest value keeps it below threshold in every hour except h6 and about a tenth of h5 and h7. Each hearing band step also showed first as negative progress for about an hour, because the window compared bins after the step with bins before it. The paper (predictive-workspace-paper #48, A.4) now pools learning progress as the largest per-module value, with the floor unchanged in form, and restarts audition's bins at each band step of A.7. The error dynamics behind valence stay a mean.

## What Changes

- The pooled `lp` is the largest windowed learning progress over the sources with a defined value, 0.0 if none. `lp+ = max(0, lp - learning_progress_floor) / (1 - learning_progress_floor)` is unchanged in form, and the error dynamics `g` stay a mean.
- The affect module reads `development.out`. On a `development.hearing_stage` event (published by the stimulus source, #569) whose stage is higher than the last stage it knows, it drops audition's windowed estimator, which restarts from audition's next report. The first stage read is stored without a restart, an equal or lower stage changes nothing, and malformed payloads are ignored. The last known stage persists in the snapshot under `hearing_stage`.
- `learning_progress_floor` becomes 0.20, the value the paper now gives (A.4, Table A1): its calibration was reproduced and re-run under the new pooling, and with the vision noise fitted to the tenth boot the frozen-control criterion is met at 0.20 (`calibration.md`).

## Capabilities

### Modified Capabilities

- `affect`: learning progress pools by the largest per-source value, and audition's bins restart at each hearing band step.

## Impact

- `kaine/modules/affect/module.py`, `config/kaine.toml` (comment), `docs/09-modules/affect.md`, tests.
- Depends on #569 (`hearing-stage-published`), which publishes the band stages; this branch is based on it.
- Behaviour: lp+ is at least as large as before whenever any processor progresses, so boredom is relieved, and curiosity built, while any one processor learns. After a band step audition's progress is undefined for two minutes and then compares post-step bins only.
