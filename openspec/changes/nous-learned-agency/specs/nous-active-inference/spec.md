## ADDED Requirements

### Requirement: Nous's actions have consequences it learns
Nous's generative model SHALL let every perceptual factor's transitions depend on the action taken, SHALL begin with the same broad, uncertain prior belief about every action's consequences, and SHALL learn those consequences from its own experience by updating its transition beliefs after each step with the action it took and the states it inferred before and after. No action's effect SHALL be written into the model.

#### Scenario: A consequence is learned
- **WHEN** one action reliably precedes a rise in salience over repeated steps
- **THEN** Nous's transition belief for that action concentrates on the rising transition

### Requirement: Uncertainty about its own actions drives exploration
Nous's expected free energy SHALL include the information to be gained about its actions' consequences, so that actions whose effects it is less sure of are worth trying, and its choices SHALL NOT collapse to a single action while its model of those consequences is uncertain.

#### Scenario: A new being samples its actions
- **WHEN** a being with an unlearned model of its actions steps through ordinary observations
- **THEN** it chooses more than one action

### Requirement: Belief carries over and the learned model is preserved
Each step's prior SHALL be the previous posterior propagated through the learned transitions under the action taken. Nous's learned transition beliefs and carried belief SHALL be part of its serialized state, and revive SHALL restore them; a snapshot without them SHALL start from the prior and say so in the log.

#### Scenario: Revive keeps the being's sense of agency
- **WHEN** a being is preserved and revived
- **THEN** its learned transition beliefs and carried belief are the ones it had, and its next decision is the one it would have made
