## ADDED Requirements

### Requirement: Short-term store defers embedding
The `short_term` buffer SHALL store the raw snapshot text and metadata without embedding. The embedder SHALL be invoked only when an entry is evicted to `episodic`, consolidated, or explicitly recalled.

#### Scenario: Short-term append does not embed
- **WHEN** `Mnemos.store` appends to `short_term`
- **THEN** `SentenceTransformer.encode` is not called

#### Scenario: Eviction embeds once
- **WHEN** the oldest short-term entry is evicted to episodic
- **THEN** the embedder runs exactly once for that entry
