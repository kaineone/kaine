## MODIFIED Requirements

### Requirement: Store and recall API
Mnemos SHALL expose `store(text, payload, affect=None, collection="short_term")` that attaches `payload` and `affect` metadata and writes to the named store. For `short_term` the text SHALL be stored without embedding; for the other collections it SHALL be embedded at store time. Mnemos SHALL expose `recall(query_text, k=5, collection="episodic")` that embeds the query, scores the named store's entries by cosine similarity to it, returns up to `k` matches as `RecalledMemory` dataclasses, and, for collections other than `short_term`, invokes the configured `EmotionalRetriggerHook` with the affect summary of those matches. For `short_term`, each entry's embedding SHALL be computed at most once per embedding space, held in memory only, and never exported or persisted; equal scores SHALL rank the more recent entry first.

#### Scenario: Store then recall returns the stored entry
- **WHEN** `store("the cat sat on the mat", payload={...})` is awaited and then `recall("cat on mat", k=1)` is awaited against the same collection
- **THEN** the returned list has length 1 and its payload equals the stored payload

#### Scenario: Recall invokes the emotional retrigger hook
- **WHEN** `recall(...)` on the episodic collection returns one or more memories with non-empty `affect` payloads and the operator has registered a hook
- **THEN** the hook callable is awaited exactly once with a summary built from the matched memories' affect

#### Scenario: Short-term recall is associative
- **WHEN** the short-term store holds an older entry about the query's topic and a newer unrelated entry, and `recall(query, k=1, collection="short_term")` is awaited
- **THEN** the older related entry is returned with a positive score

#### Scenario: Short-term embeddings are not exported
- **WHEN** short-term entries have been recalled and `export_state()` is called
- **THEN** the exported short-term entries carry their text, payload, affect and timestamp and no embedding

### Requirement: Workspace broadcasts auto-store into short-term
Mnemos SHALL produce exactly one `store` call into the short-term buffer for every `workspace.broadcast` it observes through its base module workspace consumer. The stored text SHALL be a deterministic serialization of the snapshot's selected events, naming each event's source and type with its payload after the privacy filter's vector rule has removed every vector field and every numeric list of 16 or more items. The serialization SHALL NOT include the tick index or bus entry IDs; the tick index is kept in the stored payload.

#### Scenario: One broadcast in produces one short-term entry
- **WHEN** Mnemos receives one workspace broadcast through its base module consumer with two selected events
- **THEN** the short-term buffer's size increases by exactly 1

#### Scenario: A foveated vision report stores no vectors
- **WHEN** the selected events include a `topos.report` carrying `peripheral`, `foveal` and `latent` vectors
- **THEN** the stored text contains none of those vectors' values and still names `topos:topos.report`
