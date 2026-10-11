## MODIFIED Requirements

### Requirement: Prediction error keeps the silicon semantics
Each `step(feature)` SHALL return the L2 distance between `feature` and the prediction made on the previous step (0.0 on the first step), SHALL return 0.0 and skip the step for a non-finite feature, and SHALL raise `ValueError` for a feature of the wrong length. `prediction_error_to_salience` SHALL compute the same mapping as the silicon model. A skipped step SHALL clear the stored prediction and the hidden state that produced it, so the next step returns 0.0 and makes no readout update. The model SHALL expose `last_reading_skipped`, true after a skipped step, and `last_error_defined`, false for a skipped step and for the step after it and true otherwise, including on the first step after construction or `reset()`.

#### Scenario: Load excursion raises surprise
- **WHEN** a steady feature vector is followed by one whose CPU component jumps from 0.2 to 0.9
- **THEN** the error returned for the jump is larger than every error returned during the steady phase after the first few steps

#### Scenario: A skipped reading and the next have no defined error
- **WHEN** a finite step is followed by a non-finite step and then two finite steps
- **THEN** the non-finite step returns 0.0 with `last_reading_skipped` true and `last_error_defined` false and runs no substrate tick, the next step returns 0.0 with `last_error_defined` false and no readout update, and the step after that returns a positive error with `last_error_defined` true
