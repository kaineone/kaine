## MODIFIED Requirements

### Requirement: Startup audit of Redis configuration
The bus SHALL refuse to proceed if it can confirm the Redis instance
is reachable over a routable interface without authentication, and
SHALL emit a warning (without failing) for checks it cannot verify.

For loopback hosts (`127.0.0.1`, `::1`, `localhost`), the `bind` check
SHALL be skipped because Docker port mapping (or equivalent
transport-level loopback restriction) enforces network isolation
regardless of Redis's internal bind. On loopback hosts the
`requirepass` check SHALL be advisory: if `requirepass` is unset, the
bus SHALL log a warning naming the missing protection and continue.

For non-loopback hosts the `bind` check still applies (`0.0.0.0` /
`*` cause the bus to refuse to start), and `requirepass` is mandatory
(its absence causes the bus to refuse to start). The `BusConfig`
loader follows the same rule for the password: required on non-loopback
hosts, optional on loopback hosts.

#### Scenario: Loopback host without requirepass warns but proceeds
- **WHEN** the configured host is `127.0.0.1` and Redis reports no
  `requirepass`
- **THEN** the audit logs a warning and `get_bus()` succeeds

#### Scenario: Non-loopback host without requirepass refuses to start
- **WHEN** the configured host is `10.0.0.5` and Redis reports no
  `requirepass`
- **THEN** `get_bus()` raises `BusSecurityError`

#### Scenario: Containerized Redis bound 0.0.0.0 inside container accepted
- **WHEN** the configured host is `127.0.0.1` and Redis reports
  `bind 0.0.0.0`
- **THEN** the bus does not raise `BusSecurityError` for the bind value
  and continues to the `requirepass` advisory check

#### Scenario: Non-loopback host with externally-bound Redis still refused
- **WHEN** the configured host is `10.0.0.5` and Redis reports
  `bind 0.0.0.0`
- **THEN** the bus raises `BusSecurityError`

#### Scenario: CONFIG-disabled Redis emits warning
- **WHEN** Redis returns an error to `CONFIG GET requirepass`
- **THEN** the bus logs a warning naming the unverified setting and
  continues operating

#### Scenario: Loopback config without password loads cleanly
- **WHEN** `BusConfig` is loaded with host `127.0.0.1` and no password
  in env / secrets / kaine.toml
- **THEN** `load_bus_config` returns a config with `password is None`
  and does not raise `BusConfigError`

#### Scenario: Non-loopback config without password fails fast
- **WHEN** `BusConfig` is loaded with host `10.0.0.5` and no password
  in env / secrets / kaine.toml
- **THEN** `load_bus_config` raises `BusConfigError`
