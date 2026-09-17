## ADDED Requirements

### Requirement: Bus client supports blocking reads
`kaine.bus.client.AsyncBus` SHALL expose a blocking-read API (`XREAD ... BLOCK`) for consumers that want to wait on Redis instead of polling, without breaking the existing non-blocking API.

#### Scenario: Blocking subscriber waits on Redis
- **WHEN** a consumer calls the blocking read API with a timeout
- **THEN** it returns when an event arrives or the timeout expires, issuing no Redis commands in between

#### Scenario: Non-blocking API remains available
- **WHEN** existing code calls the non-blocking read API
- **THEN** it continues to work unchanged
