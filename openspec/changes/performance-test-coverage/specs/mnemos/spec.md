## MODIFIED Requirements

### Requirement: Store and recall API
Mnemos SHALL expose `store(text, payload, affect=None, collection="short_term")` that writes `text`, `payload`, and `affect` metadata to the named store. For `short_term`, the text and metadata SHALL be stored without embedding; the embedder SHALL be invoked only when an entry is evicted to `episodic`, consolidated, or explicitly recalled. For `episodic`, `semantic`, and `procedural`, the text SHALL be embedded at store time. It SHALL expose `recall(query_text, k=5, collection="episodic")` that embeds the query, searches the named store by cosine similarity, returns up to `k` matches as `RecalledMemory` dataclasses, and invokes the configured `EmotionalRetriggerHook` with the affect summary of those matches.

#### Scenario: Store then recall returns the stored entry
- **WHEN** `store("the cat sat on the mat", payload={...})` is awaited and then `recall("cat on mat", k=1)` is awaited against the same collection
- **THEN** the returned list has length 1 and its payload equals the stored payload

#### Scenario: Recall invokes the emotional retrigger hook
- **WHEN** `recall(...)` returns one or more memories with non-empty `affect` payloads and the operator has registered a hook
- **THEN** the hook callable is awaited exactly once with a summary built from the matched memories' affect

#### Scenario: Short-term append does not embed
- **WHEN** `Mnemos.store` appends to `short_term`
- **THEN** `SentenceTransformer.encode` is not called

#### Scenario: Eviction embeds once
- **WHEN** the oldest short-term entry is evicted to episodic
- **THEN** the embedder runs exactly once for that entry
