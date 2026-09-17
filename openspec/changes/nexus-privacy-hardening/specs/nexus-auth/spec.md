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
