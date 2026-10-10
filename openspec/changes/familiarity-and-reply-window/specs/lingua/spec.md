## ADDED Requirements

### Requirement: The reply-window key is accepted
The Lingua factory SHALL accept `[lingua].outcome_reply_window_s`, which the utterance-outcome observer reads, without passing it to Lingua.

#### Scenario: Setting the reply window does not stop boot
- **WHEN** `[lingua].outcome_reply_window_s` is set to 45
- **THEN** the Lingua factory builds Lingua without error
