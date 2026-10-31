## ADDED Requirements

### Requirement: The world model answers imagination requests

The world model module SHALL consume `world_model.imagine.request` events carrying a request id, up to `max_policies` action sequences, a horizon up to `max_horizon` and a registered observation-map id. For each policy it SHALL roll its model forward from the current posterior and publish one `world_model.imagine.reply` with, per step, the mapped predicted observation, the predictive variance and the summary-part prediction.

#### Scenario: Prediction-only request

- **WHEN** the world model has no action input and receives a request with one empty policy and horizon 3
- **THEN** it replies with three steps of mapped predictions and variances for that policy

#### Scenario: Request over the bounds

- **WHEN** a request carries more than `max_policies` policies or a horizon above `max_horizon`
- **THEN** the world model replies with an error naming the bound and rolls out nothing

### Requirement: Observation maps are registered by the requester

A requester SHALL register its observation map, from the world model's observation space into the requester's own observation space, through a declared protocol before requesting with that map's id. A request naming an unregistered map SHALL receive an error reply.

#### Scenario: Unregistered map

- **WHEN** a request names a map id that no requester registered
- **THEN** the reply is an error naming the map id

### Requirement: Imagination replies are bounded in time

A reply SHALL be published within `imagine_timeout_ms` of the request, or not at all. A requester SHALL treat a missing reply as a miss and record it.

#### Scenario: A late rollout is not published

- **WHEN** a rollout would complete after `imagine_timeout_ms`
- **THEN** no reply is published for that request id

### Requirement: Imagined content stays between the two modules

Continuous content predictions in a reply SHALL be privacy-filter vector fields and SHALL NOT appear in diagnostics, the research event log or the workspace graph log.

#### Scenario: Reply in the research log

- **WHEN** the research event log records a `world_model.imagine.reply`
- **THEN** it records the request id, policy count and timing only
