## ADDED Requirements

### Requirement: The wizard offers the first configuration
The wizard's module step SHALL name the profile-defined preset "the first configuration" and SHALL read its module set from `config/profiles/first_configuration.toml`. The answer `b` SHALL keep selecting that preset.

#### Scenario: Scripted answer b
- **WHEN** the module step receives the answer `b`
- **THEN** it writes exactly the `[modules]` table of `config/profiles/first_configuration.toml`, with the recorder off, and labels the choice "first configuration"
