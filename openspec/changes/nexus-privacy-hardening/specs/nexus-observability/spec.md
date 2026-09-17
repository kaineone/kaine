## ADDED Requirements

### Requirement: Diagnostics SSE requires authentication when privileged content is enabled
When `[nexus].dev_content_override` is true or `[nexus].conversation_enabled` is true, the unified diagnostics SSE stream SHALL require the operator token. When both are false, the stream may remain unauthenticated but SHALL still carry only privacy-filtered content.

#### Scenario: Privileged SSE without token is rejected
- **WHEN** `dev_content_override` is true and a client connects to the diagnostics SSE stream without a token
- **THEN** the server responds with HTTP 401 and does not start the stream

#### Scenario: Filtered SSE remains privacy-safe
- **WHEN** `dev_content_override` is false and a client connects to the diagnostics SSE stream
- **THEN** the stream carries only content that has passed the `PrivacyFilter`

### Requirement: Metrics endpoints that expose privileged content require authentication
Any metrics or health endpoint that can expose module-internal details (e.g. raw error messages containing paths or model identifiers) SHALL require the operator token when `dev_content_override` is enabled.

#### Scenario: Metrics endpoint without token is rejected in dev mode
- **WHEN** `dev_content_override` is true and a client requests a metrics endpoint without a token
- **THEN** the server responds with HTTP 401
