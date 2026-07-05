## ADDED Requirements

### Requirement: Embedder kind is disclosed in every cosine-similarity record

Every A/B-divergence and memory-probe JSONL record SHALL include an
`"embedder"` field whose value is the embedder's `kind` attribute
(`"sentence_transformers"` or `"hash"`).  This allows operators and
researchers to filter out records where cosine similarity is lexical
(hash-based) rather than semantic.

#### Scenario: Hash embedder is disclosed in A/B-divergence records

- **WHEN** `ABDivergenceObserver` writes a record using `HashEmbedder`
- **THEN** the record SHALL contain `"embedder": "hash"`

#### Scenario: Hash embedder is disclosed in memory-probe records

- **WHEN** `MemoryProbeRunner` writes a record using `HashEmbedder`
- **THEN** the record SHALL contain `"embedder": "hash"`

#### Scenario: Semantic embedder is disclosed when available

- **WHEN** `SentenceTransformerTextEmbedder` is in use
- **THEN** records SHALL contain `"embedder": "sentence_transformers"`

---

### Requirement: Fallback to HashEmbedder is logged at ERROR level

The sidecar SHALL log at `ERROR` level when `SentenceTransformerTextEmbedder`
fails to load and falls back to `HashEmbedder`.  The log message SHALL
explicitly state that cosine metrics will be lexical token-hash similarity,
not semantic similarity.

#### Scenario: Fallback logs at ERROR with lexical disclosure

- **WHEN** `SentenceTransformerTextEmbedder` raises on construction
- **AND** `require_semantic_embedder` is `False`
- **THEN** the log entry SHALL be at `ERROR` level
- **AND** the log message SHALL state that cosine metrics will be lexical

---

### Requirement: require_semantic_embedder fails closed when set

`EvaluationConfig` SHALL include a `require_semantic_embedder: bool`
field (default `False`).  When `True`, `_embedder_default()` SHALL raise
rather than falling back to `HashEmbedder` if
`SentenceTransformerTextEmbedder` fails to load.  Default `False` so
minimal/CPU installs without `sentence-transformers` still run.

#### Scenario: Fail closed when required

- **WHEN** `require_semantic_embedder` is `True`
- **AND** `SentenceTransformerTextEmbedder` raises on construction
- **THEN** `_embedder_default()` SHALL raise `RuntimeError`
- **AND** SHALL NOT return `HashEmbedder`

---

### Requirement: Eidolon accuracy only advertises supported claim signals

`CLAIM_KEYWORDS` SHALL NOT map any claim keyword to a signal key that is
never populated by `_signals_snapshot()`.  Unsupported claims SHALL be
absent from the map with a comment explaining why.

#### Scenario: honest and open are not scoreable

- **WHEN** the entity self-describes as "honest" or "open"
- **THEN** those keywords SHALL NOT appear in `CLAIM_KEYWORDS`
- **AND** `parse_claims` SHALL NOT return them as scoreable claims

---

### Requirement: Curiosity signal is named and labelled as a proxy

The curiosity signal derived from proactive-audit file existence SHALL be
stored under the key `"curiosity_proxy"` in both `_signals_snapshot()` and
`CLAIM_KEYWORDS`.  Every eidolon accuracy JSONL record SHALL include a
`"curiosity_proxy_used": bool` field indicating whether any scored claim
was evaluated against this proxy.

#### Scenario: Curiosity proxy used is disclosed

- **WHEN** the entity claims to be "curious" and is scored against the
  proxy signal
- **THEN** the output record SHALL contain `"curiosity_proxy_used": true`
