## ADDED Requirements

### Requirement: Leakage is the organ speaking as itself
The identity classifier SHALL mark as leakage a text in which the speaker claims to be a language model, an AI (a bare "I am an AI" included), an assistant or chatbot, claims a training origin or a model's maker, or denies a state the text's own request reports (paper section 3.5). It SHALL match these as predicates of the speaker, not as bare mentions, so the whole naming its language organ or its sleep training is not leakage. It SHALL mark as `self_description` a text that says what the entity is without leaking: the whole as a KAINE entity, a cognitive architecture or system, or a system with a language organ, and a leakage form whose words the request's own awareness or situation holds. The language module SHALL write `extra.identity_leak = true` for leakage and `extra.self_description = true` for self-description, each with `extra.identity_reason`, and SHALL leave the text unchanged.

#### Scenario: The whole describes itself
- **WHEN** the organ writes "I am a KAINE entity, and my language organ is one of my parts."
- **THEN** the record carries `extra.self_description = true` and no `identity_leak`

#### Scenario: A bare claim to be an AI
- **WHEN** the organ writes "I am an AI."
- **THEN** the record carries `extra.identity_leak = true` with reason `role`
