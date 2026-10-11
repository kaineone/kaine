## ADDED Requirements

### Requirement: Studies may set the tone rule
A study configuration SHALL be allowed to set `[audition].tone_rule` and no other `[audition]` key; any other key in a study's `[audition]` table SHALL raise `ProfileError`. The repository SHALL ship `workspace_mediation_pilot_tone` (role pilot) and `workspace_mediation_tone` (role test), which run the on arm with `tone_rule = "error_ratio"`. The boot gate SHALL refuse a workspace-mediation study whose tone rule is not `error_ratio` for the two tone studies or not `categorical` for every other study.

#### Scenario: A study sets another Audition key
- **WHEN** a study file sets `[audition].alert_salience`
- **THEN** loading the configuration raises `ProfileError`

#### Scenario: An arm run with the variant's rule
- **WHEN** the operator config sets `tone_rule = "error_ratio"` and the study is `workspace_mediation_competitive`
- **THEN** the boot gate refuses the run
