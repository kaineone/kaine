## ADDED Requirements

### Requirement: Predictive processors report graded intensity
Topos, Audition's acoustic path, Soma, Chronos (once it has a temporal prediction error) and Audition's neutral tone events SHALL report the module's alert intensity when the report meets the module's alert criterion, and otherwise `I_lo + (I_hi - I_lo) * min(1, r / 2)`, where `r` is the report's prediction error over the running mean of the module's recent errors, so the competition within a tick ranks graded surprise. Each such report's payload SHALL carry a boolean `alert`.

#### Scenario: Intensity rises with the error ratio
- **WHEN** a Topos report is not an alert and its error ratio is 1.0, with baseline 0.2 and alert level 0.7
- **THEN** its intensity is 0.45

#### Scenario: An alert takes the alert level
- **WHEN** a Topos report meets the alert criterion
- **THEN** its intensity is the alert level and its payload has `alert` true
