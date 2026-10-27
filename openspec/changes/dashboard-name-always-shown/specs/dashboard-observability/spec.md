## ADDED Requirements

### Requirement: The entity name is always shown and kept current
Every dashboard page SHALL show the entity's name in its shared header, whether or not the conversation surface is enabled. The dashboard SHALL re-read the name from the self-model document and the identity file when either changes, so a name assigned after the dashboard started is shown without a restart. Before a name exists the header SHALL show the placeholder.

#### Scenario: The first configuration
- **WHEN** the dashboard runs with `conversation_enabled = false` and the identity holds "Kaine Whipple"
- **THEN** the diagnostics page header shows "Kaine Whipple"

#### Scenario: A name minted after startup
- **WHEN** the dashboard starts before the identity file exists and the cycle then writes a named identity
- **THEN** the header shows the name without a dashboard restart
