## Purpose

Protect Nexus state-changing endpoints against cross-site request forgery and DNS rebinding by validating the Origin, enforcing same-site semantics, and refusing unsafe binds unless the operator explicitly opts in.

## ADDED Requirements

### Requirement: State-changing endpoints validate Origin or Host
All state-changing Nexus endpoints SHALL validate that the request Origin matches the expected operator origin, or that the Host header matches a strict allowlist. If neither check passes, the server SHALL respond with HTTP 403 and perform no state change.

#### Scenario: Cross-origin POST is rejected
- **WHEN** a POST request arrives with an Origin header that does not match the configured operator origin
- **THEN** the server responds with HTTP 403 Forbidden and performs no state change

#### Scenario: Same-origin POST is accepted
- **WHEN** a POST arrives from the configured operator origin with a valid token
- **THEN** the server processes the request normally

### Requirement: Non-loopback binds require explicit operator opt-in
Nexus SHALL refuse to bind to `0.0.0.0` or any non-loopback interface unless the operator has explicitly set an opt-in flag and configured a token. The default bind SHALL remain `127.0.0.1`.

#### Scenario: Default loopback bind starts without opt-in
- **WHEN** Nexus starts with the shipped default `[nexus].host = "127.0.0.1"`
- **THEN** it starts normally

#### Scenario: Non-loopback bind without opt-in fails closed
- **WHEN** `[nexus].host` is set to `0.0.0.0` and the non-loopback opt-in flag is not set
- **THEN** Nexus logs a clear error and exits without opening the socket

### Requirement: SameSite cookies and CORS are configured defensively
If Nexus uses cookies or CORS, they SHALL be configured with SameSite=Strict, no wildcard origins, and no credentials shared with untrusted origins.

#### Scenario: CORS preflight from untrusted origin is rejected
- **WHEN** a preflight request arrives from an origin not in the allowlist
- **THEN** the server responds without CORS credentials and rejects the actual request

### Requirement: Host header is validated on every request
Nexus SHALL reject with HTTP 403 any request, including GET, whose `Host` header (parsed correctly for bracketed IPv6 literals such as `[::1]:8088`) is not in `[nexus].host_allowlist`, so a DNS-rebinding page cannot read any Nexus surface. State-changing requests SHALL additionally pass the Origin check. When `allowed_origins` is not configured explicitly, it SHALL be derived from the configured port, and it SHALL be overridable with `KAINE_NEXUS_ALLOWED_ORIGINS` for deployments that publish Nexus on a different host port.

#### Scenario: Rebinding GET is rejected
- **WHEN** a GET request for `/diagnostics/metrics.json` arrives with `Host: attacker.example`
- **THEN** Nexus responds 403

#### Scenario: IPv6 loopback host is accepted
- **WHEN** `host_allowlist` contains `::1` and a request arrives with `Host: [::1]:8088`
- **THEN** the Host check passes

### Requirement: Containerised Nexus starts with a loopback-only publish
The shipped container deployments SHALL set the non-loopback opt-in and the operator token through the environment (`KAINE_NEXUS_NON_LOOPBACK_ALLOWED`, `KAINE_NEXUS_TOKEN`) while publishing Nexus only on the host loopback interface, so the container starts and the dashboard remains unreachable from other hosts.

#### Scenario: Compose deployment starts
- **WHEN** the compose Nexus service starts with `KAINE_NEXUS_HOST=0.0.0.0`, `KAINE_NEXUS_NON_LOOPBACK_ALLOWED=1` and a token
- **THEN** Nexus binds and the published port is `127.0.0.1` only
