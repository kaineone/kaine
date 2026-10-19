## ADDED Requirements

### Requirement: Familiarity reaches the coupling weight
The affect module SHALL find the familiarity the social cognition module reports for the agent behind a perceived emotion: when an `social_cognition.agent_model` event carries a `source_label`, the affect module SHALL cache its familiarity under that label, which is the key it reads when it weights a perceived emotion from that channel.

#### Scenario: A familiar speaker raises the coupling weight
- **WHEN** the social cognition module publishes `social_cognition.agent_model` with `source_label` "live_mic" and familiarity 0.65, and the affect module then records a perceived emotion from "live_mic"
- **THEN** the familiarity the affect module uses for that emotion is 0.65
