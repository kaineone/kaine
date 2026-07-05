## MODIFIED Requirements

### Requirement: Startup audit of Redis configuration
The bus SHALL refuse to proceed if it can confirm the Redis instance
lacks authentication, and SHALL emit a warning (without failing) for
checks it cannot verify. The `bind` portion of the audit SHALL be
skipped when the configured `host` is a loopback name
(`127.0.0.1`, `::1`, `localhost`), because Docker port mapping (or
equivalent transport-level loopback restriction) enforces network
isolation regardless of what Redis binds inside the container. The
`requirepass` check SHALL always run.

#### Scenario: Unauthenticated Redis refuses to start the bus
- **WHEN** the configured Redis has no `requirepass` set
- **THEN** `get_bus()` raises `BusSecurityError`

#### Scenario: CONFIG-disabled Redis emits warning
- **WHEN** Redis returns an error to `CONFIG GET requirepass`
- **THEN** the bus logs a warning naming the unverified setting and
  continues operating

#### Scenario: Containerized Redis bound 0.0.0.0 inside container accepted
- **WHEN** the configured host is `127.0.0.1` and Redis reports
  `bind 0.0.0.0`
- **THEN** the bus does not raise `BusSecurityError` for the bind value
  and continues to the `requirepass` check

#### Scenario: Non-loopback host with externally-bound Redis still refused
- **WHEN** the configured host is `10.0.0.5` and Redis reports
  `bind 0.0.0.0`
- **THEN** the bus raises `BusSecurityError`
