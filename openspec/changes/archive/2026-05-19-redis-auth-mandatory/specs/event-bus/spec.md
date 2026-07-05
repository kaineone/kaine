## MODIFIED Requirements

### Requirement: Startup audit of Redis configuration
The bus SHALL refuse to proceed if it can confirm the Redis instance
lacks authentication, and SHALL emit a warning (without failing) for
checks it cannot verify. The `requirepass` check applies to **all
hosts**, loopback or not — KAINE's threat model includes future
deployment of the same code onto network-attached hosts where the
port mapping no longer enforces isolation.

The `bind` portion of the audit SHALL be skipped when the configured
`host` is a loopback name (`127.0.0.1`, `::1`, `localhost`), because
Docker port mapping (or equivalent transport-level loopback
restriction) enforces network isolation regardless of what Redis
binds inside the container. The `requirepass` check SHALL NOT be
skipped under any circumstance.

The `BusConfig` loader SHALL likewise refuse to load when no password
is available from any source, on any host.

#### Scenario: Unauthenticated Redis refuses to start the bus
- **WHEN** the configured Redis has no `requirepass` set
- **THEN** `get_bus()` raises `BusSecurityError`

#### Scenario: Loopback host without password fails the config load
- **WHEN** `BusConfig` is loaded with host `127.0.0.1` and no password
  in env / secrets / kaine.toml
- **THEN** `load_bus_config` raises `BusConfigError`

#### Scenario: Non-loopback host without password fails the config load
- **WHEN** `BusConfig` is loaded with host `10.0.0.5` and no password
  in env / secrets / kaine.toml
- **THEN** `load_bus_config` raises `BusConfigError`

#### Scenario: Containerized Redis bound 0.0.0.0 inside container accepted
- **WHEN** the configured host is `127.0.0.1` and Redis reports
  `bind 0.0.0.0`
- **THEN** the bus does not raise `BusSecurityError` for the bind value
  and continues to the (mandatory) `requirepass` check

#### Scenario: Non-loopback host with externally-bound Redis still refused
- **WHEN** the configured host is `10.0.0.5` and Redis reports
  `bind 0.0.0.0`
- **THEN** the bus raises `BusSecurityError`

#### Scenario: CONFIG-disabled Redis emits warning
- **WHEN** Redis returns an error to `CONFIG GET requirepass`
- **THEN** the bus logs a warning naming the unverified setting and
  continues operating
