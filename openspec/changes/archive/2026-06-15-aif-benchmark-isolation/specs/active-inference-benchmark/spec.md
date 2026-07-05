## ADDED Requirements

### Requirement: Both arms are driven by a matched environment

The benchmark SHALL drive the AIF arm and the RL arm from the same environment
definition for a given seed, and this confound-isolation MUST be covered by a
test. For each task in the default suite both arms MUST receive an identical
observation-space size and an identical reward structure (the env's
`reward_matching()`, reward matrices, and `optimal_return()`), and the AIF
preference `C` MUST encode the same reward magnitudes the RL baseline optimises.
Because the two arms take different actions, their realised observation streams
are not required to be byte-identical; the invariant is the shared env/reward
construction, not the per-step observations.

#### Scenario: Identical observation space and reward structure per task

- **WHEN** the environment fingerprint is taken for both arms on a default-suite
  task at a fixed seed
- **THEN** the observation-space size is identical for both arms
- **AND** the reward structure (`reward_matching`, reward matrices,
  `optimal_return`) is identical for both arms

#### Scenario: AIF preferences encode the same reward the RL arm optimises

- **WHEN** the AIF preference `C` is compared to the env's reward magnitudes
- **THEN** the win/lose reward magnitudes encoded in `C` match the env's reward
  the RL baseline optimises

#### Scenario: A mismatched reward is detected

- **WHEN** one arm is handed a tampered env whose reward differs from the other
- **THEN** the matched-environment check fails
