## ADDED Requirements

### Requirement: PrivacyFilter enforces content boundary at the bridge
The PrivacyFilter SHALL be applied at the BusBridge layer before any
event reaches an SSE client queue, NOT only at the template layer.
This guarantees a template bug cannot leak content. For diagnostics
the filter SHALL strip the following payload fields anywhere they
appear (top-level or nested in metadata):
`text`, `body`, `content`, `internal_speech`, `belief_text`,
`memory_text`, `affect_reason`, `narsese`, `transcription`.

#### Scenario: Bridge strips text field for diagnostics
- **WHEN** an event with `payload={"text": "hi", "salience": 0.8}`
  flows through the bridge with `surface=diagnostics`
- **THEN** the queued event has `payload={"salience": 0.8}` and no
  `text` key

#### Scenario: Bridge preserves text for conversation
- **WHEN** the same event flows with `surface=conversation`
- **THEN** the queued event retains the `text` field

#### Scenario: Filter strips nested content fields
- **WHEN** an event has `payload={"metadata": {"text": "leak"}}`
  going to diagnostics
- **THEN** the queued event's payload metadata does NOT contain
  `text`

### Requirement: Dev-mode override is config-gated
A `dev_content_override = true` setting in `[nexus]` SHALL permit
the diagnostics surface to receive content payloads. This option
SHALL default to `false`. The flag's current value SHALL be
visible in the diagnostics page header so operators know when
they're seeing raw content.

#### Scenario: Default config protects content
- **WHEN** an operator inspects the default `[nexus]` block in
  `config/kaine.toml`
- **THEN** they see `dev_content_override = false`

#### Scenario: Override exposes content
- **WHEN** `dev_content_override = true` and an event with `text`
  flows through diagnostics
- **THEN** the queued event retains the `text` field and the page
  shows a "dev mode" banner

### Requirement: Conversation and diagnostics are separate routers
The conversation surface SHALL live under `/` and the diagnostics
surface under `/diagnostics`. Each SHALL be implementable with
either enabled (a single surface at a time is a supported
deployment). Disabling a surface in config SHALL return 404 on its
routes.

#### Scenario: Conversation-only deployment
- **WHEN** `diagnostics_enabled = false`
- **THEN** GET `/diagnostics` returns 404
