## ADDED Requirements

### Requirement: The self-model adopts the identity's name
The self-model module SHALL take its name from the entity's identity at boot, in place of minting its own, and SHALL write it to its document when the document's name differs. Without an identity name it SHALL keep its current launch-name behaviour.

#### Scenario: A fork's copied document
- **WHEN** a fork boots with its parent's self-model document and its own identity name
- **THEN** the self-model document's name becomes the fork's identity name

### Requirement: The name stays out of the organ
The self-model module MAY publish its name in `self_model.document`, but the language module SHALL NOT cache it and no speak, think or individuation probe request SHALL contain it.

#### Scenario: No name in a request
- **WHEN** a self-model with an identity name publishes to a running language module and that module builds a speak request, a think request and a probe request
- **THEN** none of the system text, prompt or user turn contains the name

#### Scenario: A pending name during a revive
- **WHEN** the self-model starts for a revive of an unnamed bundle identity
- **THEN** it holds no name, writes no document, and takes the final name through `adopt_identity_name` once the revive has landed
