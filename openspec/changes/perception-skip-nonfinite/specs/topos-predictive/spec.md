## ADDED Requirements

### Requirement: A non-finite clip latent is skipped
When the clip latent contains a non-finite value, Topos's forward model SHALL skip the reading without appending it to the visual buffer or updating any weight, SHALL clear its stored prediction, null prediction and context, and SHALL return an error of 0, so the next reading is scored like a first reading and makes no update. Topos SHALL leave the skipped reading out of its running error window and SHALL publish no `context_gain`, `null_prediction_error` or `mean_prediction_error` for it or for the next reading. The skipped reading SHALL NOT update the change detector, the change history or the habituator; its change score SHALL be 0 and its habituation score SHALL be the last one Topos published, or null before the first. A report SHALL carry no non-finite number: a non-finite `latent`, `peripheral` or `foveal` vector SHALL be published as null. The skipped report SHALL NOT be an alert by itself.

#### Scenario: A NaN latent leaves the model and the window untouched
- **WHEN** Topos, after reports that carry a gain, receives a clip latent containing NaN
- **THEN** the forward model's buffer and weights, the running error window, the change history and the habituator's window are unchanged, and the report carries a prediction error of 0, a change score of 0, the previous habituation score, a null latent, no gain, no alert and no non-finite number

#### Scenario: The gain resumes one reading after the skip
- **WHEN** two finite clip latents follow the skipped one
- **THEN** the first of them reports no gain and the second reports a gain

#### Scenario: The hindsight pairing stays exact across a skip
- **WHEN** the live forward model and a widened copy see the same inputs, one of them non-finite
- **THEN** from the second finite input after the skip the copy's hindsight errors equal the live model's errors
