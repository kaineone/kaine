## ADDED Requirements

### Requirement: The research log carries the content readout as scalars
The curated research log SHALL copy `content_gain`, `content_cross_gain`, `content_shift_gain`, `code_sources` and `code_age_s` from the vision, audition and interoception reports, and the scalar probe gains, suspension state and dropped-error counts from `workspace_feedback.content_readout` on broadcasts. It SHALL copy no field under `latent_derived`.

#### Scenario: A report with a readout
- **WHEN** a vision report carries the five readout fields and `latent_derived.ascending_error`
- **THEN** the research record holds the five readout fields and no `latent_derived` key
