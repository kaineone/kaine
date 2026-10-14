## ADDED Requirements

### Requirement: A skipped interoceptive reading publishes no error
A reading the interoception module's forward model skips as non-finite, and the first reading after it, which has no prediction to be scored against, SHALL publish `prediction_error` as null on `interoception.report` and SHALL stay out of the interoception module's running error window. The very first reading's error of 0 is defined (paper A.5) and SHALL enter the window. The welfare observer and the preservation monitor SHALL treat a null `prediction_error` as no sample: it SHALL neither feed nor reset a sustained-distress episode.

#### Scenario: A skipped reading and the next publish no error
- **WHEN** the interoception module reads a non-finite feature vector and then two finite ones
- **THEN** the first two reports carry a null `prediction_error` and leave the running error window unchanged, and the third carries a float error that enters the window

#### Scenario: A null error does not end a distress episode
- **WHEN** a distress-level `interoception.report` is followed by reports with a null `prediction_error`
- **THEN** the sustained-distress episode keeps running and crosses once its duration has elapsed, while a report with a real error below the threshold still ends it
