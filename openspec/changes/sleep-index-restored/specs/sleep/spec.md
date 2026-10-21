## ADDED Requirements

### Requirement: The sleep index survives a restart
The sleep module SHALL carry its sleep index, the count that tags `sleep.sleep.started` and `sleep.ignition_audit` and names the intent-log corpus files, in its `serialize()` state as `sleep_index`, and SHALL restore it from that state and from the `sleep_count` of `state/lifecycle/stage.json` at `initialize()`, keeping the larger of the restored values and its current count. A `sleep_index` that is not a non-negative integer SHALL be ignored with a warning. A missing or unreadable stage file SHALL leave the count unchanged and SHALL NOT stop the module from starting.

#### Scenario: The next sleep continues the count from the stage file
- **WHEN** the stage file records `sleep_count` 4 and the sleep module starts with no checkpoint
- **THEN** the next sleep's `sleep.sleep.started` event carries `sleep_index` 5

#### Scenario: The larger record wins
- **WHEN** the resume checkpoint holds `sleep_index` 6 and the stage file records `sleep_count` 4, in either restore order
- **THEN** the sleep index is 6

#### Scenario: A malformed checkpoint value is ignored
- **WHEN** the restored state holds `sleep_index` -1, true, "3" or 2.5
- **THEN** the sleep index keeps its current value and a warning is logged
