## ADDED Requirements

### Requirement: Per-action expected free energy is correct at any planning horizon
Nous SHALL report, for each action, the lowest expected free energy among the policies whose first action is that action, SHALL choose the first action of the policy with the lowest expected free energy, and SHALL publish the configured planning horizon with its policy event.

#### Scenario: A two-step horizon
- **WHEN** Nous plans with a horizon of 2
- **THEN** each action's reported EFE is the best EFE of the two-step policies beginning with it, and the published horizon is 2
