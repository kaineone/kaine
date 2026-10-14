## ADDED Requirements

### Requirement: Language publishes an aggregate language.out stream
The language module SHALL publish an aggregate `language.out` event in addition to the mode-specific `language.external` and `language.internal` streams. The aggregate event SHALL carry `mode`, `text`, and metadata so that consumers following the documented `<module>.out` convention receive the language organ's events. The cycle engine and registry SHALL read `language.out`.

#### Scenario: Engine reads Language events via language.out
- **WHEN** the language module emits an external or internal speech event
- **THEN** a corresponding aggregate event appears on `language.out` and the cycle engine ingests it into the workspace selection path

#### Scenario: Mode-specific streams remain available
- **WHEN** the language module emits external speech
- **THEN** the event appears on both `language.external` and `language.out`

### Requirement: Language reuses its own stream constants
The language module SHALL publish to `EXTERNAL_STREAM`, `INTERNAL_STREAM`, and the aggregate `language.out` using module-level constants everywhere, never re-hardcoding the literal strings.

#### Scenario: Internal publish uses constant
- **WHEN** `kaine/modules/language/module.py` is inspected
- **THEN** all `bus.publish` calls use `EXTERNAL_STREAM`, `INTERNAL_STREAM`, or an aggregate-stream constant
