## ADDED Requirements

### Requirement: The self-model adopts the identity's name
The self-model module SHALL take its name from the entity's identity at boot, in place of minting its own, and SHALL write it to its document when the document's name differs. Without an identity name it SHALL keep its current launch-name behaviour.

#### Scenario: A fork's copied document
- **WHEN** a fork boots with its parent's self-model document and its own identity name
- **THEN** the self-model document's name becomes the fork's identity name
