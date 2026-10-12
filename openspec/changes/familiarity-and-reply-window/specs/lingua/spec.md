## ADDED Requirements

### Requirement: The reply-window key is accepted
The Language factory SHALL accept `[lingua].outcome_reply_window_s`, which the utterance-outcome observer reads, without passing it to Language.

#### Scenario: Setting the reply window does not stop boot
- **WHEN** `[lingua].outcome_reply_window_s` is set to 45
- **THEN** the Language factory builds Language without error
