## MODIFIED Requirements

### Requirement: Epistemic actions ride the intent path
Nous SHALL NOT invoke effectors and SHALL NOT publish intents. For a chosen `request_think`, `request_speak` or `request_maintenance` it SHALL publish a content-free `nous.proposal` event (`proposal_id`, `action`, `kind` ∈ {think, speak, rest}, `step`, `preference`) whose salience rises with the chosen action's preference. `no_op` SHALL publish nothing. Only Volition turns a proposal into an intent, and only after the proposal has become conscious in a non-inhibited broadcast, so that Syneidesis inhibition, Volition's guards and Praxis whitelists remain in control of all outward action.

#### Scenario: Action becomes a proposal, not an intent or a call
- **WHEN** the engine selects `request_think`
- **THEN** Nous publishes a `nous.proposal` with `kind` `think`, and publishes no `intent.*` event and makes no effector call

#### Scenario: Action becomes an intent, not a direct call
- **WHEN** the engine selects an information-seeking action and its proposal becomes conscious in a non-inhibited broadcast
- **THEN** Volition, not Nous, publishes the corresponding intent, and Nous makes no direct effector call

#### Scenario: No-op proposes nothing
- **WHEN** the engine selects `no_op`
- **THEN** no `nous.proposal` is published

## ADDED Requirements

### Requirement: Nous learns from the action actually taken
Before each engine step Nous SHALL record, as the action taken, the action of its most recent proposal if Volition reported it realized, and `no_op` otherwise, including when no outcome has arrived. Outcomes that arrive after the step they concern SHALL be counted and not applied.

#### Scenario: A declined proposal is learned as no-op
- **WHEN** Volition reports a `think` proposal declined because the snapshot was inhibited
- **THEN** the next Nous step learns from `no_op` as the taken action

#### Scenario: A realized proposal is learned as taken
- **WHEN** Volition reports a `speak` proposal realized
- **THEN** the next Nous step learns from `request_speak` as the taken action
