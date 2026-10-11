## ADDED Requirements

### Requirement: A reading without a defined error teaches no unexpected error
When the forward model reports that its last reading has no defined error (`last_error_defined` is false: a reading skipped as non-finite, or the first reading after one), Soma SHALL report an `unexpected_error` of 0 for that reading and SHALL leave its expected-error estimates unchanged. This SHALL hold for a forward model that exposes per-channel residuals and for one that does not.

#### Scenario: A scalar-only model's skipped reading teaches nothing
- **WHEN** a forward model without `last_residuals` reports a reading without a defined error after fifty defined ones
- **THEN** that reading's `soma.report` carries a null `prediction_error` and an `unexpected_error` of 0, and the expected and spread estimates are unchanged
