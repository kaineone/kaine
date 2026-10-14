## ADDED Requirements

### Requirement: The reply-window key is accepted
The language module factory SHALL accept `[language].outcome_reply_window_s`, which the utterance-outcome observer reads, without passing it to the language module.

#### Scenario: Setting the reply window does not stop boot
- **WHEN** `[language].outcome_reply_window_s` is set to 45
- **THEN** the language module factory builds the language module without error
