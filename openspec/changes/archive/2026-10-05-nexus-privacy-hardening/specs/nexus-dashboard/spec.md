## ADDED Requirements

### Requirement: Operator controls require authentication and CSRF protection
All operator controls exposed by the Nexus dashboard (cycle freeze/unfreeze, cycle rate adjustment, fork/merge actions, perception toggle, and perception locus selection) SHALL be gated by both the operator token and CSRF/Origin validation. The controls SHALL NOT be reachable by unauthenticated or cross-origin requests.

#### Scenario: Unauthenticated freeze request is rejected
- **WHEN** a POST request arrives at the cycle freeze endpoint without a valid operator token
- **THEN** the server responds with HTTP 401 and the entity's freeze state is unchanged

#### Scenario: Cross-origin fork request is rejected
- **WHEN** a cross-origin POST arrives at a fork/merge endpoint with a valid token but failing Origin validation
- **THEN** the server responds with HTTP 403 and no fork or merge is performed

### Requirement: Privileged content surfaces require authentication
The conversation surface and any dashboard panel that renders raw message text, beliefs, memory bodies, internal speech, or affect reasons SHALL require the operator token before serving content.

#### Scenario: Conversation page without token is rejected
- **WHEN** `conversation_enabled` is true and a client requests the conversation page without a token
- **THEN** the server responds with HTTP 401 and renders no privileged content

#### Scenario: Dev-content diagnostics without token is rejected
- **WHEN** `dev_content_override` is true and a client requests the diagnostics stream without a token
- **THEN** the server responds with HTTP 401 and does not stream raw content
