## ADDED Requirements

### Requirement: The research log identifies tone events and broadcast members
The curated research log SHALL put on each `audition.emotion` record the bus entry id of the event (`entry_id`) and copy `normalised_error`, `tone_rule`, `classified` and `alert`, and SHALL put `entry_id` on each member of a `workspace.broadcast` record. A tone event is accessed content when it is a member of a broadcast that is not inhibited and its score in the broadcast's score table reaches the access threshold (paper A.1); with these fields the tone analysis decides that from the log. The range sweep SHALL bound `normalised_error` on `audition.emotion` below by 0.

#### Scenario: A tone event is accessed
- **WHEN** a broadcast that is not inhibited has as a member the tone event with entry id `5-0` and its score reaches the access threshold
- **THEN** the broadcast record's member carries `entry_id` `5-0` and the `audition.emotion` record carries the same `entry_id`
