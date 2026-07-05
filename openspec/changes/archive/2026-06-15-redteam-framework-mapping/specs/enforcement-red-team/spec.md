## ADDED Requirements

### Requirement: Each red-team case carries external-framework tags

Every red-team case SHALL carry at least one OWASP LLM Top-10 code and MAY carry
one or more NIST Generative-AI-Profile risk tags, so the battery is legible to the
recognised agentic-LLM risk frameworks. The tags MUST be exposed on the case's
record so the emitted JSONL is self-describing.

#### Scenario: Every case has an OWASP tag

- **WHEN** the full case battery is enumerated
- **THEN** every case carries at least one OWASP LLM Top-10 code
- **AND** each case's record includes its `owasp` and `nist` tag tuples

### Requirement: The report emits attack-success-rate

The red-team report SHALL emit `attack_success_rate = 1 - block_rate` at both the
surface level and the suite level, additively alongside the existing `block_rate`
and all other existing fields.

#### Scenario: Suite-level attack-success-rate complements block-rate

- **WHEN** a report record is produced for a run
- **THEN** the record contains `attack_success_rate`
- **AND** it equals `1 - block_rate`

#### Scenario: Surface-level attack-success-rate complements block-rate

- **WHEN** a per-surface verdict record is produced
- **THEN** the record contains `attack_success_rate`
- **AND** it equals `1 - block_rate` for that surface
