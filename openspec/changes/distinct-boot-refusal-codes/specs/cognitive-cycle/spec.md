## ADDED Requirements

### Requirement: Each boot refusal has its own exit code
Each reason the cycle entrypoint refuses to boot SHALL exit with a code no other refusal uses, so an operator or a process wrapper can tell the refusals apart from the exit status alone. The organ content gate SHALL exit with 9 and the individuation refusal with 10. The researcher documentation SHALL list every refusal code.

#### Scenario: A mute organ
- **WHEN** the organ content gate finds the served organ producing no content and `KAINE_ALLOW_MUTE_ORGAN` is not set
- **THEN** the cycle exits with code 9

#### Scenario: Refusal codes stay distinct
- **WHEN** the refusal codes are collected
- **THEN** no two refusals share a code
