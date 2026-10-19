## ADDED Requirements

### Requirement: The affect state event carries the valence-target terms
Every `affect.state` payload, periodic or after an affective reset, SHALL carry, in addition to its existing keys, the terms behind the valence target computed at publication: for each source in the fixed table (`vision`, `audition`) the keys `<source>_error_fast`, `<source>_error_slow` and `<source>_progress` (the fast and slow time-decayed means of its raw prediction error and its clipped relative fall `g_m`); `signed_progress` (the pooled `g`, paper `lp`); `learning_progress` (paper `lp+`); `wellness`; `wellness_fast`, `wellness_slow` and `wellness_change`; `pleasantness`; and `valence_target` under the active `valence_rule`. A source absent from the trackers SHALL give null for its three keys, and a source whose slow mean is not above 1e-9 SHALL give a null progress. The wellness means SHALL be null before the first wellness report, and `wellness_change` SHALL be the value the error-dynamics rule adds (0.0 before reports). Every value SHALL be a finite number or null, and the key set SHALL NOT depend on which sources have reported. The values SHALL equal the ones the update step uses, and the affect dynamics SHALL be unchanged.

#### Scenario: Values match the trackers
- **WHEN** vision has reported known errors at known times, interoception has reported known wellness values, and the module publishes `affect.state`
- **THEN** `vision_error_fast`, `vision_error_slow` and `vision_progress` equal the time-decayed means and `g_m` computed from those reports, `signed_progress` and `learning_progress` equal `_progress()`, `wellness_change` equals the fast minus the slow wellness mean, and `valence_target` equals `clip(tanh(valence_progress_gain * g) + wellness_change, -1, 1)`

#### Scenario: An absent source is null
- **WHEN** only vision has reported
- **THEN** `audition_error_fast`, `audition_error_slow` and `audition_progress` are null and the payload has the same keys as when both sources have reported

#### Scenario: An unlisted source adds no keys
- **WHEN** a perceptual report arrives from a source outside the table
- **THEN** it counts in `signed_progress` and the payload's key set is unchanged
