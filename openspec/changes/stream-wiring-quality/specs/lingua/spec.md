## ADDED Requirements

### Requirement: Lingua output streams are discoverable by the cycle engine
Either Lingua SHALL publish an aggregate `lingua.out` stream that the cycle engine and registry read, OR the engine/registry SHALL be updated to read Lingua's real streams (`lingua.external`, `lingua.internal`) and `tests/test_config_stream_wiring.py` SHALL reflect the actual wiring. In either case, consumers following the documented `<module>.out` convention SHALL receive the language organ's events.

#### Scenario: Engine reads Lingua events
- **WHEN** Lingua emits an external or internal speech event
- **THEN** the cycle engine ingests it into the workspace selection path

#### Scenario: No phantom stream is read
- **WHEN** the registry's active streams are enumerated
- **THEN** `lingua.out` is not present unless Lingua actually publishes to it

### Requirement: Lingua reuses its own stream constants
Lingua SHALL publish to `EXTERNAL_STREAM` and `INTERNAL_STREAM` constants everywhere, never re-hardcoding the literal strings.

#### Scenario: Internal publish uses constant
- **WHEN** `kaine/modules/lingua/module.py` is inspected
- **THEN** all `bus.publish` calls use `EXTERNAL_STREAM` or `INTERNAL_STREAM` variables
