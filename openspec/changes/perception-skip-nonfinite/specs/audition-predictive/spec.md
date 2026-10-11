## ADDED Requirements

### Requirement: A non-finite auditory input is skipped
When an acoustic embedding or a tone feature vector contains a non-finite value, Audition's forward model for that path SHALL skip the reading without appending it to the auditory buffer or updating any weight, SHALL clear its stored prediction, null prediction and context, and SHALL return an error of 0, so the next reading is scored like a first reading and makes no update. Audition SHALL leave the skipped reading out of that path's running error window. For the acoustic path it SHALL publish no `context_gain`, `null_prediction_error` or `mean_prediction_error` for the skipped reading or the next one, SHALL NOT update the previous embedding or the change history, and SHALL report a change score of 0. The skipped report SHALL NOT be an alert by itself.

#### Scenario: A NaN acoustic embedding leaves the model and the window untouched
- **WHEN** Audition, after acoustic reports that carry a gain, receives an acoustic embedding containing NaN
- **THEN** the acoustic forward model's buffer and weights are unchanged, the running error window and the change history are unchanged, the report carries a prediction error of 0, a change score of 0, no gain and no alert

#### Scenario: The gain resumes one reading after the skip
- **WHEN** two finite acoustic embeddings follow the skipped one
- **THEN** the first of them reports no gain and the second reports a gain

#### Scenario: The hindsight pairing stays exact across a skip
- **WHEN** the live forward model and a widened copy see the same inputs, one of them non-finite
- **THEN** from the second finite input after the skip the copy's hindsight errors equal the live model's errors
