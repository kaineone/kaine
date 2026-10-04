## ADDED Requirements

### Requirement: Lingua's HTTP backend is named for its protocol
Lingua's default backend SHALL be named `"openai"`, for the OpenAI-compatible HTTP server that serves the organ. The name `"ollama"` SHALL remain accepted as an alias that builds the same client. The in-process `llama_cpp` backend SHALL fall back to `"openai"`. The shipped tier profiles SHALL select `"openai"`.

#### Scenario: Both names build the same client
- **WHEN** Lingua's backend is `"openai"`, `"ollama"`, or unset
- **THEN** the registry builds the OpenAI-compatible HTTP client

#### Scenario: The shipped profiles use the canonical name
- **WHEN** the tier2 or tier3 profile is read
- **THEN** its `[lingua].backend` is `"openai"`
