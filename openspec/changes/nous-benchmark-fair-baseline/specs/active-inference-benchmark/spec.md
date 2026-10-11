## ADDED Requirements

### Requirement: The Q-learning baseline remembers the episode's observations
The benchmark's tabular Q-learning baseline SHALL key its action values by the history of observations in the current episode, up to a configured memory that defaults to the task's horizon, so the baseline has the same information as an agent that keeps beliefs. A memory of zero SHALL reproduce the memoryless learner, kept as an explicit control. The memory used SHALL be recorded with the baseline's hyperparameters.

#### Scenario: The cue can be carried to the arm
- **WHEN** two T-maze episodes reach the same location with observation histories that differ only in the cue observation
- **THEN** a baseline with the default memory indexes them by different state keys

#### Scenario: Memoryless control
- **WHEN** the baseline is configured with memory zero
- **THEN** its state key is the current observation only

### Requirement: The active-inference agent samples its policy from the policy posterior
When given a random generator, the benchmark's active-inference agent SHALL sample its policy from the policy posterior that the active-inference engine computes from expected free energy and policy precision, and SHALL act on that policy's first action. The runner SHALL give each evaluation seed its own generator derived from that seed, so results reproduce. Without a generator the agent SHALL select the policy with the lowest expected free energy.

#### Scenario: Sampling reproduces under a seed
- **WHEN** the benchmark is run twice with the same seeds
- **THEN** the agent's actions and the verdicts are identical
