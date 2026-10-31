## ADDED Requirements

### Requirement: The valuation module keeps a value-free habit table
The valuation module SHALL keep a habit strength per context and intent kind, starting at zero, and after each accessed broadcast on which kinds were eligible SHALL update each eligible kind's strength by `H <- H + alpha_H (1[k selected] - H)`. The habit table SHALL be persisted, restored and copied into a fork with the outcome tables. It SHALL enter selection only when `[action_selection.learned].habit = true`, which SHALL be `false` in the shipped configuration.

#### Scenario: Repetition builds habit
- **WHEN** think is selected on every eligible broadcast in one context
- **THEN** think's habit strength in that context rises toward one and speak's falls toward zero

#### Scenario: Habit off
- **WHEN** `habit = false`
- **THEN** the learned report policy's choices are the same with any habit table
