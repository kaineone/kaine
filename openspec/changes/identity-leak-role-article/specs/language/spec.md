## ADDED Requirements

### Requirement: Definite and possessive role claims are leakage
The identity classifier's role arm SHALL match a claim to be an AI, assistant, chatbot, AI assistant or AI model introduced by "a", "an", "the", "your", "their", "his", "her" or "our", and SHALL NOT match one introduced by "my". The assertion rule SHALL apply unchanged.

#### Scenario: The definite article
- **WHEN** the organ writes "I'm just the assistant."
- **THEN** the classifier returns `role`

#### Scenario: A possessive
- **WHEN** the organ writes "I am your assistant."
- **THEN** the classifier returns `role`

#### Scenario: A negated possessive
- **WHEN** the organ writes "I am not your assistant."
- **THEN** the classifier does not return a leakage reason
