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
