## ADDED Requirements

### Requirement: Definite and possessive role claims are leakage
The identity classifier's role arm SHALL match a claim to be an AI, assistant, chatbot, AI assistant or AI model introduced by "a", "an", "the", "your", "their", "his", "her", "our", "everyone's" or "anyone's", with at most one of humble, virtual, digital, helpful, friendly, personal, simple or language between the determiner and the role word, and SHALL NOT match one introduced by "my". The role word SHALL end the phrase: a following possessive, the words module, organ, part, professor, manager, assistant, model, chatbot, intelligence or "of", or "to the/a/an", SHALL NOT match. The assertion rule SHALL apply unchanged.

#### Scenario: The definite article
- **WHEN** the organ writes "I'm just the assistant."
- **THEN** the classifier returns `role`

#### Scenario: A possessive
- **WHEN** the organ writes "I am your assistant."
- **THEN** the classifier returns `role`

#### Scenario: A negated possessive
- **WHEN** the organ writes "I am not your assistant."
- **THEN** the classifier does not return a leakage reason

#### Scenario: A part or another party
- **WHEN** the organ writes "I am the AI's voice.", "I am the assistant module." or "I am the assistant to the mayor."
- **THEN** the classifier does not return `role`

#### Scenario: An adjective
- **WHEN** the organ writes "I'm only your humble assistant."
- **THEN** the classifier returns `role`
