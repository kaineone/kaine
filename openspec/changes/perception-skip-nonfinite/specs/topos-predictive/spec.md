## ADDED Requirements

### Requirement: A non-finite clip latent is skipped
When the clip latent contains a non-finite value, the vision module's forward model SHALL skip the reading without appending it to the visual buffer or updating any weight, SHALL clear its stored prediction, null prediction and context, and SHALL return an error of 0. The next reading then has no prediction to be scored against and makes no update. Only a defined error SHALL enter the vision module's running error window: the very first reading's error of 0 is defined (paper A.2), while a skipped reading and the first reading after a skip have no defined error, SHALL stay out of the window, and SHALL publish `prediction_error` as null with a `normalised_error` of 0. The vision module SHALL publish no `context_gain`, `null_prediction_error` or `mean_prediction_error` for either report. The skipped reading SHALL NOT update the change detector, the change history or the habituator; its change score SHALL be 0 and its habituation score SHALL be the last one the vision module published, or null before the first. A report SHALL carry no non-finite number: a non-finite `latent`, `peripheral` or `foveal` vector SHALL be published as null. The skipped report SHALL NOT be an alert by itself.

#### Scenario: A NaN latent leaves the model and the window untouched
- **WHEN** the vision module, after reports that carry a gain, receives a clip latent containing NaN
- **THEN** the forward model's buffer and weights, the running error window, the change history and the habituator's window are unchanged, and the report carries a null prediction error, a change score of 0, the previous habituation score, a null latent, no gain, no alert and no non-finite number

#### Scenario: The gain resumes one reading after the skip
- **WHEN** two finite clip latents follow the skipped one
- **THEN** the first of them publishes a null prediction error, stays out of the window and reports no gain, and the second is scored, enters the window and reports a gain

#### Scenario: Periodic gaps put no zeros in the window
- **WHEN** non-finite latents recur, each followed by two finite ones
- **THEN** the running error window holds only the first reading's 0 and the errors of the scored readings

#### Scenario: The hindsight pairing stays exact across a skip
- **WHEN** the live forward model and a widened copy see the same inputs, one of them non-finite
- **THEN** from the second finite input after the skip the copy's hindsight errors equal the live model's errors, and in the running module the shadows' buffers equal the live buffer after every report
