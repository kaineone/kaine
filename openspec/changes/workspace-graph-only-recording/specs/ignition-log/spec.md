## ADDED Requirements

### Requirement: The ignition log is the workspace-graph record and only the operator deletes it
The ignition log SHALL be the record of the global workspace graph kept by research runs: one row per successful broadcast, at full rate, never sampled. It is kept for the paper analysis and then as world-model training data. It SHALL never be deleted or purged automatically; its sink SHALL use no retention period, and deletion SHALL be an operator action.

#### Scenario: Old files are kept
- **WHEN** the ignition log starts while files from earlier days exist in its directory
- **THEN** none of them is removed

#### Scenario: Every broadcast is recorded
- **WHEN** N broadcasts succeed with the log enabled
- **THEN** the log holds N rows
