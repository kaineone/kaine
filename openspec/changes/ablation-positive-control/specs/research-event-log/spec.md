## ADDED Requirements

### Requirement: The research log records the positive control's results
The curated research log SHALL subscribe to `positive_control.out` and copy, from each `positive_control.result` event, only `processor`, `n_reports`, `ig_with`, `ig_without`, `ig_noise`, `effect`, `noise_effect`, `min_effect`, `min_reports`, `snr`, `detected`, `noise_detected`, `passed`, `failed` and `final`.

#### Scenario: A result is logged
- **WHEN** a processor publishes a `positive_control.result` event with an extra field
- **THEN** the research record carries every result field and not the extra one
