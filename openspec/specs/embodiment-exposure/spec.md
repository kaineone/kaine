# embodiment-exposure Specification

## Purpose
How configuration decides which of an embodiment adapter's channels and action families the entity can perceive and act through. The `expose_<name>` keys under `[mundus.<adapter>]` are routed by the names the selected body declares, so a key either takes effect or refuses boot; it is never silently ignored.

## Requirements

### Requirement: Exposure keys are routed by the body's declared names
For the selected embodiment adapter, each `expose_<name>` key in `[mundus.<adapter>]` SHALL be routed by the names the adapter declares in its capabilities: a declared continuous channel SHALL set that channel's continuous exposure, and a declared action family SHALL set that family's symbolic exposure. A name the adapter declares as neither SHALL refuse boot with a configuration error naming the key and the adapter's declared channels and families. Undeclared continuous channels SHALL stay unexposed, as they are by default.

#### Scenario: A continuous channel is exposed from configuration
- **WHEN** the stub body is selected and `[mundus.stub].expose_drive = true`
- **THEN** the `drive` continuous channel is exposed and the other continuous channels stay unexposed

#### Scenario: A misspelled key is refused
- **WHEN** `[mundus.stub].expose_drvie = true`
- **THEN** boot refuses with a configuration error naming `expose_drvie` and the stub's declared names
