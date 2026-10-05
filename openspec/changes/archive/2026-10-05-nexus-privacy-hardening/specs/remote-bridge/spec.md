## ADDED Requirements

### Requirement: Non-loopback bridge binds require a token
The remote bridge SHALL refuse to bind to any address other than `127.0.0.1` unless a non-empty operator token is configured. The default bind SHALL remain loopback and the default token SHALL remain empty.

#### Scenario: Loopback bind starts without token
- **WHEN** the bridge is enabled with the default `host = "127.0.0.1"` and no token
- **THEN** it starts normally, relying on the tailnet ACL as the primary boundary

#### Scenario: Non-loopback bind without token fails closed
- **WHEN** the bridge is configured with `host = "0.0.0.0"` and an empty token
- **THEN** the bridge logs a clear error and refuses to start

### Requirement: Token is not transmitted in query string or subprotocol
The bridge SHALL accept the operator token via the `Authorization: Bearer <token>` header for non-browser clients. The token SHALL NOT be accepted in the WebSocket query string or as a `Sec-WebSocket-Protocol` subprotocol value, so it does not appear in URL history, referrers, or server logs.

#### Scenario: Browser client uses header-based authentication
- **WHEN** a browser client connects with the token in the query string
- **THEN** the server rejects the connection with HTTP 401

#### Scenario: Non-browser client uses Bearer header
- **WHEN** a client connects with `Authorization: Bearer <token>`
- **THEN** the server accepts the connection if the token is valid
