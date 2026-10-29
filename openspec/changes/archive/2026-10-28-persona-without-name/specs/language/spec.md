## ADDED Requirements

### Requirement: The organ's request carries no name
The language module SHALL NOT put the entity's name in the organ's system text, prompt or user turn, whether the name comes from the self-model document or from configuration. `[language].persona_name` SHALL be retired: a config that sets it SHALL boot with a warning and the value SHALL be ignored. `PERSONA_TEMPLATE_VERSION` SHALL be "7". The persona digest SHALL keep null in its name slot, so a config without `persona_name` keeps its digest.

#### Scenario: A named self-model
- **WHEN** a request is assembled with a self-model document whose name is "Kaine Nova"
- **THEN** neither its system text nor its prompt contains "Kaine Nova" or "My name is"

#### Scenario: The retired key
- **WHEN** the language module is built from a config that sets `persona_name`
- **THEN** boot logs a warning and the system text contains no name
