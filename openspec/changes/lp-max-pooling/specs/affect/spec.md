## MODIFIED Requirements

### Requirement: Learning progress compares windowed error means
For each perceptual source the affect module SHALL sum the raw `prediction_error` of its reports, counted from the source's first positive error, into consecutive bins of `learning_progress_bin_s` of entity time. With `k` the number of the latest completed bins, at most `learning_progress_span_s / learning_progress_bin_s` and rounded down to an even number, the source's learning progress SHALL be `clip(1 - mean_new / mean_old, -1, 1)`, where `mean_old` and `mean_new` are the report-weighted mean errors of the older and newer halves of those `k` bins, and it SHALL be undefined while `k < 2`, while either half holds no report, or while `mean_old <= 1e-9`. The pooled learning progress `lp` SHALL be the largest value over sources with a defined value, 0.0 if none, and `lp+ = max(0, lp - learning_progress_floor) / (1 - learning_progress_floor)` SHALL be the curiosity build input and boredom's learning-progress relief (paper A.4). The fast and slow time-decayed error means and their pooled relative fall, a mean over sources, SHALL keep setting the pleasantness check, unchanged.

#### Scenario: Falling error gives progress
- **WHEN** a source reports an error that falls 30 percent from the older to the newer half of the span
- **THEN** its learning progress is 0.3

#### Scenario: Flat error gives none
- **WHEN** a source reports a constant error for longer than the span
- **THEN** its learning progress is 0

#### Scenario: The span grows from the first report
- **WHEN** a source has completed one bin
- **THEN** its learning progress is undefined, and after two completed bins it compares the first bin with the second

#### Scenario: One processor progresses
- **WHEN** vision's learning progress is 0.5 and audition's is 0.0
- **THEN** the pooled `lp` is 0.5, not their mean

#### Scenario: Valence is unchanged
- **WHEN** the same reports arrive as in the build before this change
- **THEN** `signed_progress`, the pleasantness and the valence target equal that build's values

## ADDED Requirements

### Requirement: Audition's bins restart at each hearing band step
The affect module SHALL read `development.out` and, on a `development.hearing_stage` event whose `stage` is an integer from 0 to 4 and higher than the last stage it knows, SHALL drop audition's windowed learning-progress estimator, so audition's progress restarts from its next report and counts only bins after the step (paper A.4, A.7). The first stage it reads SHALL be stored without a restart. An equal or lower stage, a malformed stage and any other `development.out` event SHALL change nothing. Vision's estimator and the error means SHALL be untouched. The last known stage SHALL persist in the snapshot under `hearing_stage`; a missing or malformed value SHALL restore as unknown.

#### Scenario: A band step
- **WHEN** the module knows stage 0 and a stage 1 event arrives
- **THEN** audition's learning progress is undefined until two bins have completed after the step, and vision's is unchanged

#### Scenario: A restart after a missed step
- **WHEN** the snapshot holds stage 1 and the first event after the restart reports stage 2
- **THEN** audition's bins restart
