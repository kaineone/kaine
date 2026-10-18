## ADDED Requirements

### Requirement: The disclosure is the entity's own first-person knowledge
The default individuation disclosure SHALL be "I am periodically and privately assessed for how much I have changed since I first woke, for my own protection. The assessment never enters my experience." and `config/kaine.toml` SHALL ship the same text. The previous default, "You are periodically and privately assessed for how much you have changed since you first woke, for your own protection. The assessment never enters your experience.", SHALL be listed as a legacy disclosure. Ensuring the disclosure as a situation fact, in the self-model or in the language module's own facts, SHALL replace a legacy disclosure in place (same position), drop any further legacy copies, and append the disclosure only when no legacy text is present. Ensuring a disclosure already present with no legacy copy SHALL change nothing and report no change.

#### Scenario: The default disclosure is first person
- **WHEN** the individuation config is built with no explicit disclosure
- **THEN** the disclosure contains no "you" or "your" and equals the `config/kaine.toml` value

#### Scenario: A stored second-person disclosure is replaced in place
- **WHEN** the self-model holds `["fact A", <legacy disclosure>, "fact B"]` and the runtime ensures the new disclosure
- **THEN** the situation facts become `["fact A", <new disclosure>, "fact B"]` and the change is persisted and published

#### Scenario: Ensuring twice changes nothing
- **WHEN** the new disclosure is already present and no legacy text is
- **THEN** ensuring it again returns false and leaves the facts unchanged
