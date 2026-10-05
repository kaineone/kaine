## ADDED Requirements

### Requirement: One definition of the shared summary statistics
The system SHALL define the mean, the population standard deviation and the linear-interpolation percentile once, in a stdlib-only module under `kaine.experiment`. The stability harness, the ignition-study analysis and the prediction-error observer SHALL use those definitions and SHALL NOT define their own. Each statistic SHALL return 0.0 on empty input, and the standard deviation SHALL return 0.0 for fewer than two values.

#### Scenario: Empty input yields zero
- **WHEN** the mean or the percentile is taken of an empty sequence, or the standard deviation of a single value
- **THEN** the result is 0.0

#### Scenario: The percentile agrees with linear interpolation
- **WHEN** the percentile of a sequence is taken at any percentage from 0 to 100
- **THEN** it equals numpy's default linear-interpolation percentile of that sequence

#### Scenario: The instruments share the definitions
- **WHEN** the stability harness, the ignition-study analysis or the prediction-error observer summarises its values
- **THEN** it uses the shared definitions
