## ADDED Requirements

### Requirement: The first configuration attends to learning progress
The first-configuration profile SHALL set `[workspace].salience_goal_factor = "interest"`. The shipped `config/kaine.toml` default SHALL stay `"static"`, and every workspace-mediation study arm SHALL set it to `"static"`.

#### Scenario: The profile selects the interest factor
- **WHEN** the configuration is loaded with the first-configuration profile
- **THEN** `[workspace].salience_goal_factor` is `"interest"` and `interest_gain` is 0.5

#### Scenario: Study arms rank by intensity and novelty
- **WHEN** any `workspace_mediation_*` study is loaded on the first-configuration profile
- **THEN** `[workspace].salience_goal_factor` is `"static"`
