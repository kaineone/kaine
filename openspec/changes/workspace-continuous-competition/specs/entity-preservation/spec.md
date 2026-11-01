## ADDED Requirements

### Requirement: Bundles and manifests record the workspace supply
Preservation bundles and run manifests SHALL record `workspace_supply` (`held_pool` when the candidate pool is on, `tick` otherwise) and `workspace_capacity`. A bundle or manifest without them SHALL be read as `tick` with capacity 5.

#### Scenario: A bundle preserved with the pool on
- **WHEN** an entity running with the pool on at capacity 1 is preserved
- **THEN** its bundle manifest records `workspace_supply` `held_pool` and `workspace_capacity` 1

### Requirement: A revive across a workspace change needs the operator's decision
A revive whose bundle's supply or capacity differs from the running configuration's SHALL refuse with the revive-refused exit code and a message naming the change, unless that revive request sets `accept_workspace_change = true`. An accepted revive SHALL record the acknowledgement in the run manifest.

#### Scenario: An old bundle into the pool
- **WHEN** a bundle preserved before this change is revived into a configuration with the pool on, without the acknowledgement
- **THEN** the revive refuses and the message says the being would move to a different workspace

#### Scenario: An old bundle with the pool off
- **WHEN** the same bundle is revived into a configuration with the pool off and `top_k = 5`
- **THEN** the revive proceeds without the acknowledgement

#### Scenario: The operator decides
- **WHEN** the first revive sets `accept_workspace_change = true`
- **THEN** the revive proceeds and the run manifest records the acknowledgement
