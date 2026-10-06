## ADDED Requirements

### Requirement: The intent-expression log is encrypted at rest
When state encryption is enabled, every line Lingua writes to `state/lingua/intent_expression.jsonl` SHALL be its own AES-256-GCM envelope. Every reader of that log and of its rotated corpus SHALL decrypt line by line, accepting legacy plaintext lines. On its first write under encryption, Lingua SHALL rewrite a live log that holds plaintext lines so that every line is an envelope. Hypnos SHALL do the same for the being's own rotated corpus files at sleep. Backups, `state/forks` and preservation bundles SHALL never be rewritten.

#### Scenario: Lines are envelopes on disk
- **WHEN** encryption is enabled and Lingua logs an utterance
- **THEN** the appended line is an encryption envelope and no generated text appears in the file's raw bytes

#### Scenario: A legacy plaintext log is migrated once
- **WHEN** encryption is enabled and the live log holds plaintext lines from before encryption
- **THEN** the first write rewrites the log atomically so every line is an envelope, and undecryptable envelope lines are kept byte for byte
