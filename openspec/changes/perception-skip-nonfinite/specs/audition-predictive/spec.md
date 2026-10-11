## ADDED Requirements

### Requirement: A non-finite auditory input is skipped
When an acoustic embedding or a tone feature vector contains a non-finite value, Audition's forward model for that path SHALL skip the reading without appending it to the auditory buffer or updating any weight, SHALL clear its stored prediction, null prediction and context, and SHALL return an error of 0. The next reading then has no prediction to be scored against and makes no update. Only a defined error SHALL enter that path's running error window: the very first reading's error of 0 is defined (paper A.2), while a skipped reading and the first reading after a skip SHALL stay out of the window and SHALL publish `prediction_error` as null (on `audition.perception` for the acoustic path, on `audition.emotion` and `audition.transcription` for the tone path). For the acoustic path Audition SHALL publish no `context_gain`, `null_prediction_error` or `mean_prediction_error` for either report, SHALL NOT update the previous embedding or the change history on the skipped reading, and SHALL report a change score of 0 for it. The skipped report SHALL NOT be an alert by itself and SHALL carry no non-finite number.

#### Scenario: A NaN acoustic embedding leaves the model and the window untouched
- **WHEN** Audition, after acoustic reports that carry a gain, receives an acoustic embedding containing NaN
- **THEN** the acoustic forward model's buffer and weights, the running error window and the change history are unchanged, and the report carries a null prediction error, a change score of 0, no gain, no alert and no non-finite number

#### Scenario: A NaN tone feature vector is skipped
- **WHEN** the tone path's feature vector contains NaN
- **THEN** the tone forward model's buffer and weights and the tone error window are unchanged, the emotion event carries a null prediction error and no non-finite number, and the next window also stays out of the tone error window

#### Scenario: The gain resumes one reading after the skip
- **WHEN** two finite acoustic embeddings follow the skipped one
- **THEN** the first of them publishes a null prediction error, stays out of the window and reports no gain, and the second is scored, enters the window and reports a gain

#### Scenario: The hindsight pairing stays exact across a skip
- **WHEN** the live forward model and a widened copy see the same inputs, one of them non-finite
- **THEN** from the second finite input after the skip the copy's hindsight errors equal the live model's errors
