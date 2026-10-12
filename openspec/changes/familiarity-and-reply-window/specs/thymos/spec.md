## ADDED Requirements

### Requirement: Familiarity reaches the coupling weight
Affect SHALL find the familiarity Social cognition reports for the agent behind a perceived emotion: when an `empatheia.agent_model` event carries a `source_label`, Affect SHALL cache its familiarity under that label, which is the key it reads when it weights a perceived emotion from that channel.

#### Scenario: A familiar speaker raises the coupling weight
- **WHEN** Social cognition publishes `empatheia.agent_model` with `source_label` "live_mic" and familiarity 0.65, and Affect then records a perceived emotion from "live_mic"
- **THEN** the familiarity Affect uses for that emotion is 0.65
