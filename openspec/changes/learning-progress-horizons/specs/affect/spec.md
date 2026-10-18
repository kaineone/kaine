## ADDED Requirements

### Requirement: Learning progress compares windowed error means
For each perceptual source the affect module SHALL sum the raw `prediction_error` of its reports, counted from the source's first positive error, into consecutive bins of `learning_progress_bin_s` of entity time. With `k` the number of the latest completed bins, at most `learning_progress_span_s / learning_progress_bin_s` and rounded down to an even number, the source's learning progress SHALL be `clip(1 - mean_new / mean_old, -1, 1)`, where `mean_old` and `mean_new` are the report-weighted mean errors of the older and newer halves of those `k` bins, and it SHALL be undefined while `k < 2`, while either half holds no report, or while `mean_old <= 1e-9`. The pooled learning progress `lp` SHALL be the mean over sources with a defined value, 0.0 if none, and `lp+ = max(0, lp - learning_progress_floor) / (1 - learning_progress_floor)` SHALL be the curiosity relief strength and `1 - lp+` its build input (paper A.4). The fast and slow time-decayed error means and their pooled relative fall SHALL keep setting the pleasantness check, unchanged.

#### Scenario: Falling error gives progress
- **WHEN** a source reports an error that falls 30 percent from the older to the newer half of the span
- **THEN** its learning progress is 0.3 and `lp+` relieves curiosity

#### Scenario: Flat error gives none
- **WHEN** a source reports a constant error for longer than the span
- **THEN** its learning progress is 0 and curiosity is not relieved

#### Scenario: The span grows from birth
- **WHEN** a source has completed one bin
- **THEN** its learning progress is undefined, and after two completed bins it compares the first bin with the second

#### Scenario: Valence is unchanged
- **WHEN** the same reports arrive as in the build before this change
- **THEN** `signed_progress`, the pleasantness and the valence target equal that build's values

### Requirement: Learning-progress configuration
The `[affect]` section SHALL accept `learning_progress_span_s` (default 5400.0) and `learning_progress_bin_s` (default 60.0). Both SHALL be finite and positive, and the span SHALL be an even whole number of bins, at least 2, or construction SHALL raise `ValueError`.

#### Scenario: A span that is not an even number of bins is refused
- **WHEN** the affect module is built with `learning_progress_span_s = 150.0` and `learning_progress_bin_s = 60.0`
- **THEN** it raises `ValueError`

### Requirement: Learning-progress bins persist
The affect snapshot SHALL carry each source's completed bins, its current bin and the entity time elapsed in it under `learning_progress_bins`, with the bin width, and a restore SHALL reproduce the source's learning progress. A snapshot without the key, an entry with invalid numbers, or one saved with a different bin width SHALL leave that source's bins empty; more bins than the span SHALL keep the newest. The bins SHALL carry through sleep like the error means.

#### Scenario: Round trip
- **WHEN** a module with bins for vision and audition is serialized and a fresh module deserializes the state
- **THEN** both report the same learning progress

#### Scenario: Old snapshot
- **WHEN** a snapshot saved before this change is restored
- **THEN** the error means are restored and the learning-progress bins start empty

### Requirement: The affect state event carries the windowed progress terms
Every `affect.state` payload SHALL carry `vision_learning_progress` and `audition_learning_progress`, each source's windowed learning progress or null while undefined, and `signed_learning_progress`, the pooled `lp`. `learning_progress` SHALL be `lp+` from the windows. Every value SHALL be finite or null and the key set SHALL be fixed.

#### Scenario: Terms match the estimator
- **WHEN** vision has reported for several bins and the module publishes `affect.state`
- **THEN** `vision_learning_progress` equals the estimator's value, `audition_learning_progress` is null, and `signed_learning_progress` equals `vision_learning_progress`
