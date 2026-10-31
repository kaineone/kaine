## ADDED Requirements

### Requirement: A revive across a workspace supply change needs the operator's decision
Preservation bundles and run manifests SHALL record `workspace_supply`, `held_pool_v1` for this design. A revive of a bundle whose `workspace_supply` differs from the running cycle's, or is absent, SHALL refuse with the revive-refused exit code and a message naming the change, unless that revive request sets `accept_workspace_supply_change = true`. An accepted revive SHALL record the acknowledgement in the run manifest.

#### Scenario: An old bundle
- **WHEN** a bundle preserved before this change is revived without the acknowledgement
- **THEN** the revive refuses and the message says the being would move to a different workspace

#### Scenario: The operator decides
- **WHEN** the same revive sets `accept_workspace_supply_change = true`
- **THEN** the revive proceeds and the run manifest records the acknowledgement
