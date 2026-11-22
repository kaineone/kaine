## ADDED Requirements

### Requirement: Cross-module event types are registered with a payload model
Every event type that a module other than its producer reads SHALL be registered in `kaine/bus/event_types.py` with its owner, a payload model, its declared consumers and a version. Payload models SHALL accept extra keys and SHALL reject a missing or mistyped declared field.

#### Scenario: A producer's payload satisfies its model
- **WHEN** a producer's own code builds a payload for a registered type in its unit tests
- **THEN** the registered model validates it

#### Scenario: A dropped field fails a test, not a run
- **WHEN** a producer stops writing a declared field of a registered type
- **THEN** the producer contract test fails and names the type and the field

#### Scenario: Development mode reports a mismatch at publish
- **WHEN** `KAINE_DEV_VALIDATE=1` and a module publishes a registered type whose payload fails its model
- **THEN** `publish` raises; with the variable unset it logs the mismatch and publishes

### Requirement: The envelope carries an optional payload version
`Event` SHALL accept `payload_version`, an optional integer. An absent value SHALL mean version 1, so every existing stored entry decodes unchanged.

#### Scenario: Old entries decode
- **WHEN** a stored entry without `payload_version` is read
- **THEN** it decodes and its payload version reads as 1
