## ADDED Requirements

### Requirement: The affective reset is requested by a command event

The sleep module SHALL perform its last phase by publishing `sleep.affective_reset.requested` with the sleep index and a request id, and SHALL wait for a matching `affect.affective_reset.done` up to `[sleep].affective_reset_timeout_s`. It SHALL record the phase's success from the acknowledgement. A timeout SHALL record the phase as failed with reason `no_ack`, and the sleep SHALL still end with `sleep.sleep.completed`. The sleep module SHALL NOT hold a reference to the affect module object.

#### Scenario: Acknowledged reset

- **WHEN** a sleep reaches its last phase and the affect module acknowledges the request with success
- **THEN** the completion event's `affective_reset` phase is recorded as successful

#### Scenario: No acknowledgement

- **WHEN** the affect module does not acknowledge within the timeout
- **THEN** the phase is recorded with `success == False` and reason `no_ack`, and `sleep.sleep.completed` is still published

#### Scenario: A cancelled sleep still requests the reset

- **WHEN** a sleep is cancelled before its last phase
- **THEN** exactly one `sleep.affective_reset.requested` is published and an aborted `sleep.sleep.completed` follows
