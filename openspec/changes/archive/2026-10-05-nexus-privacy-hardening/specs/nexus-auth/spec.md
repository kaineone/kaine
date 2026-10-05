## Purpose

Provide operator authentication for the Nexus dashboard and control endpoints so that state-changing operations and privileged content can only be performed or viewed by a holder of the operator token.

## ADDED Requirements

### Requirement: Operator token gates all state-changing Nexus endpoints
All Nexus HTTP endpoints that mutate entity state SHALL require a valid operator token. This includes cycle freeze/unfreeze, cycle rate changes, fork creation and merge, perception toggle, perception locus changes, and any future control endpoints added under `/diagnostics/cycle/*`, `/diagnostics/forks/*`, `/diagnostics/merges/*`, or `/diagnostics/perception/*`.

#### Scenario: Request without token is rejected
- **WHEN** a POST request arrives at any state-changing Nexus endpoint without a token
- **THEN** the server responds with HTTP 401 Unauthorized and performs no state change

#### Scenario: Request with valid token is accepted
- **WHEN** a POST request arrives with the configured operator token in the `Authorization: Bearer <token>` header
- **THEN** the server processes the request normally

### Requirement: Operator token gates privileged read surfaces
When `[nexus].conversation_enabled` is true or `[nexus].dev_content_override` is true, the diagnostics SSE stream, conversation endpoints, and any endpoint that can return raw message text, beliefs, memory bodies, internal speech, or affect reasons SHALL require the operator token.

#### Scenario: Diagnostics SSE without token is rejected when override is enabled
- **WHEN** `dev_content_override` is true and a client requests the diagnostics SSE stream without a token
- **THEN** the server responds with HTTP 401 and does not start the stream

#### Scenario: Conversation endpoint without token is rejected
- **WHEN** `conversation_enabled` is true and a client requests the conversation page or its API without a token
- **THEN** the server responds with HTTP 401

### Requirement: Token is configured at deployment time
The operator token SHALL be supplied via an environment variable or a secrets file, never hardcoded in the repository, never logged, and never returned in API responses. The shipped default SHALL leave the token empty, which disables all privileged surfaces until an operator explicitly configures a token.

#### Scenario: Empty token disables privileged surfaces
- **WHEN** the token is not configured
- **THEN** state-changing endpoints return HTTP 401 and conversation/dev-override surfaces are disabled

#### Scenario: Token is not present in repository or logs
- **WHEN** the repository is inspected or logs are searched
- **THEN** no plaintext operator token appears in source files, config files, or log output

### Requirement: Browser operator session
Nexus SHALL provide a login page at `/login` and a `POST /auth/login` endpoint that accepts the operator token once. On success it SHALL issue an opaque random session identifier in a cookie marked `HttpOnly`, `SameSite=Strict`, `Path=/` (and `Secure` when the request arrived over HTTPS), and SHALL return a separate random per-session key in the response body exactly once; the browser keeps that key in origin-scoped storage and Nexus SHALL NOT return it again. Because browsers share cookies across all ports of a host, the cookie alone SHALL authenticate only safe methods (GET, HEAD); every state-changing request on a gated endpoint SHALL additionally carry the session key in an `X-Nexus-Session-Key` header, compared in constant time. A valid `Authorization: Bearer` token SHALL authenticate any request. The operator token itself SHALL NOT be stored in the cookie or returned in any response. Sessions SHALL expire after a configurable idle period and after an absolute maximum age, SHALL be discarded when Nexus restarts, and SHALL be revocable through `POST /auth/logout`. A correct token SHALL always be able to log in; failed logins SHALL be rate limited.

#### Scenario: Dashboard works after login
- **WHEN** an operator logs in at `/login` with the configured token and the dashboard then loads pages, opens the diagnostics `EventSource`, and issues state-changing `fetch` calls that carry the session key
- **THEN** those requests succeed

#### Scenario: Stolen cookie cannot change state
- **WHEN** a request presents a valid session cookie but no matching `X-Nexus-Session-Key` on a state-changing gated endpoint such as `/diagnostics/cycle/freeze`
- **THEN** Nexus responds 401 and performs no state change

#### Scenario: Unauthenticated browser navigation is redirected
- **WHEN** a browser without a session requests an HTML page that requires the operator token
- **THEN** Nexus redirects it to `/login` instead of returning a bare 401

#### Scenario: Wrong tokens are throttled but the right token is not locked out
- **WHEN** repeated `POST /auth/login` requests present a wrong token and then the correct token is presented
- **THEN** the wrong attempts return 401 without a cookie (429 once the failure limit is reached) and the correct token still logs in

### Requirement: Health endpoint stays unauthenticated
`/diagnostics/health.json` reports dependency status only and SHALL remain reachable without authentication regardless of `conversation_enabled` or `dev_content_override`, so container health checks keep working. Every other diagnostics, conversation and evaluation read surface SHALL use the same authentication as the rest of the privileged surface.

#### Scenario: Health check with conversation enabled
- **WHEN** `conversation_enabled` is true and an unauthenticated client requests `/diagnostics/health.json`
- **THEN** Nexus responds 200

### Requirement: Operator token is read only from the environment or the secrets file
Nexus SHALL read the operator token from `KAINE_NEXUS_TOKEN` or from `[nexus].operator_token` in `config/secrets.toml` (the environment wins), and SHALL refuse to start when a non-empty `operator_token` appears in the tracked `config/kaine.toml`. Token comparison SHALL use a constant-time comparison that does not reveal the token length. Nexus SHALL refuse to start with a configured token shorter than 32 characters, SHALL strip surrounding whitespace from the environment token, and SHALL refuse to start on a malformed operator overlay or secrets file rather than silently ignoring it.

#### Scenario: Token in secrets.toml
- **WHEN** `config/secrets.toml` sets `[nexus].operator_token` and `KAINE_NEXUS_TOKEN` is unset
- **THEN** Nexus uses that token

#### Scenario: Token committed to the tracked config
- **WHEN** `config/kaine.toml` contains a non-empty `[nexus].operator_token`
- **THEN** Nexus refuses to start and names the file to move the token out of
