## MODIFIED Requirements

### Requirement: Embedder kind is disclosed in every cosine-similarity record

Every A/B-divergence and memory-probe JSONL record SHALL include an
`"embedder"` field whose value is the embedder's `kind` attribute
(`"numpy_minilm"`, `"sentence_transformers"` or `"hash"`). This allows
operators and researchers to filter out records where cosine similarity is
lexical (hash-based) rather than semantic.

#### Scenario: Hash embedder is disclosed in A/B-divergence records

- **WHEN** `ABDivergenceObserver` writes a record using `HashEmbedder`
- **THEN** the record SHALL contain `"embedder": "hash"`

#### Scenario: Hash embedder is disclosed in memory-probe records

- **WHEN** `MemoryProbeRunner` writes a record using `HashEmbedder`
- **THEN** the record SHALL contain `"embedder": "hash"`

#### Scenario: Semantic embedder is disclosed when available

- **WHEN** the configured semantic embedder is in use
- **THEN** records SHALL contain its kind, `"numpy_minilm"` or `"sentence_transformers"`

### Requirement: Fallback to HashEmbedder is logged at ERROR level

The sidecar SHALL use the text embedder configured by `[embedding]` and SHALL
load it when it starts. When that load fails and `require_semantic_embedder`
is false, it SHALL log at `ERROR` level and fall back to `HashEmbedder`. The
log message SHALL explicitly state that cosine metrics will be lexical
token-hash similarity, not semantic similarity. A semantic embedder that failed
to load SHALL never be used to produce a record.

#### Scenario: Fallback logs at ERROR with lexical disclosure

- **WHEN** the configured embedder fails to load at sidecar start
- **AND** `require_semantic_embedder` is `False`
- **THEN** the log entry SHALL be at `ERROR` level
- **AND** the log message SHALL state that cosine metrics will be lexical
- **AND** records SHALL carry `"embedder": "hash"`

### Requirement: require_semantic_embedder fails closed when set

`EvaluationConfig` SHALL include a `require_semantic_embedder: bool`
field (default `False`). When `True`, the sidecar SHALL refuse to start
rather than falling back to `HashEmbedder` if the configured text embedder
fails to load.

#### Scenario: Fail closed when required

- **WHEN** `require_semantic_embedder` is `True`
- **AND** the configured embedder fails to load at sidecar start
- **THEN** the sidecar's start SHALL raise `RuntimeError`
- **AND** SHALL NOT fall back to `HashEmbedder`
