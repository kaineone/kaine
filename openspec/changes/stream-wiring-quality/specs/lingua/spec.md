## ADDED Requirements

### Requirement: Language publishes an aggregate lingua.out stream
Language SHALL publish an aggregate `lingua.out` event in addition to the mode-specific `lingua.external` and `lingua.internal` streams. The aggregate event SHALL carry `mode`, `text`, and metadata so that consumers following the documented `<module>.out` convention receive the language organ's events. The cycle engine and registry SHALL read `lingua.out`.

#### Scenario: Engine reads Language events via lingua.out
- **WHEN** Language emits an external or internal speech event
- **THEN** a corresponding aggregate event appears on `lingua.out` and the cycle engine ingests it into the workspace selection path

#### Scenario: Mode-specific streams remain available
- **WHEN** Language emits external speech
- **THEN** the event appears on both `lingua.external` and `lingua.out`

### Requirement: Language reuses its own stream constants
Language SHALL publish to `EXTERNAL_STREAM`, `INTERNAL_STREAM`, and the aggregate `lingua.out` using module-level constants everywhere, never re-hardcoding the literal strings.

#### Scenario: Internal publish uses constant
- **WHEN** `kaine/modules/lingua/module.py` is inspected
- **THEN** all `bus.publish` calls use `EXTERNAL_STREAM`, `INTERNAL_STREAM`, or an aggregate-stream constant
