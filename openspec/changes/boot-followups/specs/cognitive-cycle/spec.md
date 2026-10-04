## ADDED Requirements

### Requirement: A failed boot releases what it holds
When a boot phase raises, the cycle entrypoint SHALL cancel every boot task already started, stop the welfare producer and close the bus, and SHALL then re-raise. It SHALL NOT shut the modules down, so a half-built boot never writes module state over a saved copy. On every early exit, anything that reads the bus SHALL stop before the bus closes.

#### Scenario: A phase raises after the bus opened
- **WHEN** a boot phase raises after the bus, the welfare producer and a boot task exist
- **THEN** the task is cancelled, the welfare producer is stopped and the bus is closed
- **AND** no module is shut down
- **AND** the exception propagates

#### Scenario: A revive is refused
- **WHEN** a revive is refused after the modules initialised
- **THEN** the modules shut down, then the welfare producer stops, then the bus closes
