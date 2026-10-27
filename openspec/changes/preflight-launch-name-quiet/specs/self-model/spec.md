## ADDED Requirements

### Requirement: Preflight self-models do not report launch names
A self-model instance built for a preflight check SHALL NOT log a launch-name assignment that names a surname. The entity's own self-model SHALL log its name once at boot, saying whether it was adopted from the identity or minted.

#### Scenario: A preflight run
- **WHEN** the preflight builds and initializes a throwaway self-model
- **THEN** no log line names a launch surname
