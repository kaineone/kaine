## ADDED Requirements

### Requirement: The research log records conversation-memory counts without content
While conversation memory is enabled, the research log SHALL record a `conversation_memory.counts` event at each sleep onset and at shutdown. Its fields SHALL be integers, floats or lists of integers only. It SHALL hold no text and no trace ids. A plain-words readout tool SHALL print these counts per run.

#### Scenario: Counts carry no content
- **WHEN** the counts event is recorded
- **THEN** every field is an integer, a float or a list of integers

### Requirement: The counts event has an exact allowlist
The `conversation_memory.counts` allowlist SHALL be exactly:
- `heard_accessed`;
- `comprehension_requests`, `comprehension_failed`, `comprehension_deferred`, `comprehension_interrupted`;
- `gists_stored`, `gists_masked`, `gists_withheld`, `gists_truncated`;
- `mean_gist_tokens`;
- `longest_shared_run_hist`;
- `episodes`, `episode_accounts`;
- `conversation_recalls`, `conversation_recalls_accessed`;
- `utterance_traces_pruned`;
- `collection_size`.

Any other field SHALL be dropped.

#### Scenario: An unlisted field is dropped
- **WHEN** a counts payload carries a field outside the allowlist
- **THEN** the recorded event omits that field

### Requirement: The external-utterance log passes the overlap guard
While conversation memory is enabled, the external-utterance research log SHALL record each utterance's text after the overlap guard's masking.

#### Scenario: An echo is masked in the research record
- **WHEN** the entity repeats seven consecutive heard words aloud and the external-utterance log is enabled
- **THEN** the recorded text holds `(their words)` in place of the run
