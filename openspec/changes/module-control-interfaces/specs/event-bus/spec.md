## ADDED Requirements

### Requirement: Producers declare payload contracts per event type

Each module SHALL declare, for every event type it publishes, a payload model in a contracts module beside the producer. Each producer's tests SHALL validate the payloads it emits against that model.

#### Scenario: A producer emits a field its model lacks

- **WHEN** a producer's test publishes an event whose payload carries a field not in its declared model
- **THEN** the producer's contract test fails naming the event type and the field

### Requirement: Consumers declare the payload fields they read

Each consumer of another module's events SHALL declare the event types and payload fields it reads. A test SHALL fail when a declared consumer field is absent from the producer's model or has an incompatible type.

#### Scenario: Consumer reads a field the producer renamed

- **WHEN** a producer's model renames `selected_events` to `selected` and a consumer still declares `selected_events`
- **THEN** `tests/test_payload_contracts.py` fails naming the consumer, the event type and the field

### Requirement: Publish-time payload checking is opt-in

`[bus].validate_payloads` SHALL accept `off`, `warn` and `enforce`, and SHALL default to `off`. Under `warn`, a payload that fails its model SHALL be published and logged once per event type. Under `enforce`, it SHALL raise `EventValidationError` before any Redis command.

#### Scenario: Default publishes unchecked payloads

- **WHEN** `[bus].validate_payloads` is unset and an event's payload does not match its model
- **THEN** the event is published and nothing is logged about its payload

#### Scenario: Enforce rejects a malformed payload

- **WHEN** `[bus].validate_payloads = "enforce"` and an event's payload does not match its model
- **THEN** `bus.publish` raises `EventValidationError` and the stream is unchanged
