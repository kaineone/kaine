## ADDED Requirements

### Requirement: Access-rule failures bound a run's admissibility
`scan_run` SHALL report the share of broadcast ticks whose access decision failed (`access_rule_failures`), and SHALL report a run inadmissible, with that reason, when the share exceeds `max_access_rule_failure_share`, supplied by the caller as data with a default of 0.001. A run on the default account SHALL report a share of zero.

#### Scenario: A plugin rule that fails often makes the run inadmissible
- **WHEN** 0.5 percent of a run's broadcast ticks record an access-rule failure and the bound is 0.001
- **THEN** `scan_run` reports `admissible = false` and gives the failure share as the reason

#### Scenario: A default run reports no failures
- **WHEN** a run on the default account is scanned
- **THEN** its access-rule failure share is zero and does not affect admissibility
