## ADDED Requirements

### Requirement: Empatheia operator sources are checked when the config loads
Config loading SHALL refuse a `[empatheia].operator_sources` that is not a list of strings, naming the key, before the boot opens any resource.

#### Scenario: A string instead of a list
- **WHEN** `[empatheia].operator_sources` is the string `"live_mic"`
- **THEN** loading the config fails with a shape error naming `empatheia.operator_sources`
