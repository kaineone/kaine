# mnemos Specification

## Purpose
Mnemos is KAINE's episodic memory module. This capability covers its KAINE-owned, authenticated Qdrant store and collections, the store and recall API with its shared text embedder, automatic storage of workspace broadcasts, consolidation from short-term to episodic memory, and spontaneous cue-based recall in the live loop.

## Requirements

### Requirement: Containerized Qdrant required for KAINE-owned memory
The repository SHALL ship `compose/qdrant.yml` running an authenticated
Qdrant container exposed at `127.0.0.1:6533:6333`. The API key SHALL be
required via `${KAINE_QDRANT_API_KEY:?...}` — compose SHALL refuse to
start without it. Persistent storage SHALL be backed by a named volume
`kaine-qdrant-data`.

#### Scenario: docker compose refuses to start unauthenticated
- **WHEN** an operator runs `docker compose -f compose/qdrant.yml up`
  without `KAINE_QDRANT_API_KEY` set in env or `compose/.env`
- **THEN** compose exits non-zero before starting the container

### Requirement: Bootstrap script mirrors the Redis pattern
The repository SHALL ship `scripts/qdrant-bootstrap.sh` that brings the
Qdrant bus from a fresh clone to a healthy, authenticated,
`/readyz`-OK state in one invocation. It SHALL generate (or reuse
with `--keep-key`) a strong API key, write it atomically into
`compose/.env`, mirror it into `config/secrets.toml`'s `[qdrant]`
section, recreate the container, and confirm `/readyz` returns 200.

#### Scenario: Fresh clone reaches /readyz in one command
- **WHEN** an operator on a fresh clone runs
  `bash scripts/qdrant-bootstrap.sh`
- **THEN** the container is healthy and a GET on
  `http://127.0.0.1:6533/readyz` with the api-key header returns 200

### Requirement: Four CLS-separated collections
Mnemos SHALL manage four memory stores with the build-prompt-prescribed
names: `short_term` (in-process buffer, not persisted), `episodic`,
`semantic`, and `procedural` (persisted in Qdrant). The collection
prefix `mnemos_` SHALL be configurable.

#### Scenario: Four collections exist after initialize
- **WHEN** `Mnemos.initialize` completes against a fresh Qdrant
- **THEN** the three Qdrant collections `mnemos_episodic`,
  `mnemos_semantic`, `mnemos_procedural` exist and accept points

#### Scenario: Short-term is in-memory only
- **WHEN** Mnemos is shut down and reinitialized
- **THEN** the short-term buffer is empty (no Qdrant collection by
  that name exists)

### Requirement: Store and recall API
Mnemos SHALL expose `store(text, payload, affect=None, collection="short_term")`
that embeds `text`, attaches `payload` and `affect` metadata, and writes
to the named store. It SHALL expose
`recall(query_text, k=5, collection="episodic")` that embeds the query,
searches the named store by cosine similarity, returns up to `k`
matches as `RecalledMemory` dataclasses, and invokes the configured
`EmotionalRetriggerHook` with the affect summary of those matches.

#### Scenario: Store then recall returns the stored entry
- **WHEN** `store("the cat sat on the mat", payload={...})` is awaited
  and then `recall("cat on mat", k=1)` is awaited against the same
  collection
- **THEN** the returned list has length 1 and its payload equals the
  stored payload

#### Scenario: Recall invokes the emotional retrigger hook
- **WHEN** `recall(...)` returns one or more memories with non-empty
  `affect` payloads and the operator has registered a hook
- **THEN** the hook callable is awaited exactly once with a summary
  built from the matched memories' affect

### Requirement: Short-term consolidates into episodic at capacity
Mnemos SHALL evict the oldest short-term entry into the episodic
collection on the next `store` call whenever the short-term buffer is
at its configured capacity (default 128). The original payload,
affect, and timestamp SHALL be preserved across the move.

#### Scenario: 129th store evicts oldest to episodic
- **WHEN** short-term capacity is 128 and the 129th `store` call
  arrives
- **THEN** the oldest of the 128 prior entries is moved into the
  episodic collection and the short-term buffer's size is 128

### Requirement: Workspace broadcasts auto-store into short-term
Mnemos SHALL produce exactly one `store` call into the short-term
buffer for every `workspace.broadcast` it observes through its base
module workspace consumer. The stored text SHALL be a deterministic
serialization of the snapshot's selected events.

#### Scenario: One broadcast in produces one short-term entry
- **WHEN** Mnemos receives one workspace broadcast through its base
  module consumer with two selected events
- **THEN** the short-term buffer's size increases by exactly 1

### Requirement: Diagnostics-only bus event for recall
Each `recall` call SHALL publish a `mnemos.recall` event to `mnemos.out`
containing `count`, `collection`, `query_length`, and the maximum
affect intensity among the returned memories — but SHALL NOT include
the memory contents or the raw query text. The privacy boundary from
build prompt §8.3 applies here even pre-Nexus.

#### Scenario: Recall publishes count without contents
- **WHEN** `recall(query, k=5)` returns 3 matched memories
- **THEN** the published `mnemos.recall` event has `count == 3` and
  no fields containing the memory texts or the query string

### Requirement: Default Mnemos config and disabled-by-default
The repository SHALL ship a `[mnemos]` block in `config/kaine.toml`
with default values for `backend` (`qdrant`), `collection_prefix`,
`short_term_capacity`, `recall_top_k`, `baseline_salience` and
`alert_salience`, and an `[embedding]` block with `backend` (`numpy`),
`model_id` and `device`. `[mnemos]` SHALL NOT accept `embedder_model_id`
or `device`: boot SHALL reject either with an error naming the
`[embedding]` key that replaces it. The `[modules].mnemos = false` flag
SHALL keep first boot from auto-registering Mnemos.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[mnemos]` section with the documented keys, an `[embedding]` section, and `[modules].mnemos == false`

#### Scenario: The old embedder keys are refused
- **WHEN** an operator config sets `[mnemos].embedder_model_id` or `[mnemos].device`
- **THEN** boot fails with an error naming `[embedding].model_id` or `[embedding].device`

### Requirement: Spontaneous cue-based recall in the live loop

Mnemos SHALL perform cue-based recall in the live loop: on an experiential
workspace broadcast that carries a meaningful cue, it derives a query from the
conscious snapshot, calls `recall()`, and publishes the recalled memories as
`mnemos.recall` events, so recalled context re-enters the workspace and reaches
downstream consumers (e.g. Thymos). Recall SHALL occur before the snapshot is
stored for that tick
(so the cue retrieves prior memories, not the just-stored one). Recall SHALL be
throttled by a cooldown so it does not fire on every tick, and SHALL be skipped
when there is no meaningful cue. Recall SHALL run regardless of
`snapshot.inhibited` (recall is internal cognition, not an outward action).
Storing the snapshot each experiential tick SHALL continue unchanged.

#### Scenario: A cued experiential tick triggers recall

- **WHEN** an experiential broadcast with a non-empty cue occurs and the recall
  cooldown has elapsed
- **THEN** Mnemos calls recall and publishes a `mnemos.recall` event

#### Scenario: Cooldown suppresses repeated recall

- **WHEN** experiential broadcasts occur faster than the recall cooldown
- **THEN** Mnemos recalls at most once per cooldown window

#### Scenario: No cue, no recall

- **WHEN** a broadcast carries no meaningful cue
- **THEN** Mnemos performs no recall

#### Scenario: Recall is not inhibition-gated

- **WHEN** a cued experiential broadcast is inhibited and the cooldown elapsed
- **THEN** Mnemos still performs recall (recall is cognition, not action)

#### Scenario: Storing still happens every experiential tick

- **WHEN** an experiential broadcast occurs
- **THEN** Mnemos stores the snapshot as before, independent of whether recall
  fired

### Requirement: Mnemos recall does not fabricate empty success on storage failure

`QdrantStorage.search()` SHALL raise `StorageError` (not return `[]`) when
the Qdrant backend operation fails.  `Mnemos.recall()` SHALL catch
`StorageError`, log it at `error` level, and publish a `mnemos.recall` event
carrying `"error": true` and `"error_detail"` — never a fake `count=0` result
that looks like a successful empty search.

`InMemoryStorage.search()` is unaffected: missing collections return `[]`
normally (that is a valid empty result, not a storage failure).

#### Scenario: Qdrant backend failure

- **WHEN** `QdrantStorage.search()` encounters any exception from the client
- **THEN** it raises `StorageError` with a descriptive message
- **AND** does NOT return `[]`

#### Scenario: Mnemos recall on StorageError

- **WHEN** `Mnemos.recall()` encounters a `StorageError`
- **THEN** it logs the error at `logging.ERROR` level
- **AND** publishes `mnemos.recall` with `"error": true`
- **AND** returns `[]` to the caller (graceful empty, not a fake success)
- **AND** the published event does NOT carry `"error": true` on a successful recall

#### Scenario: Successful recall

- **WHEN** `Mnemos.recall()` completes without error
- **THEN** `mnemos.recall` is published with real `count` and no `"error"` key

### Requirement: One shared text embedder with a torch-free default
KAINE SHALL build a single text embedder per registry from the `[embedding]` configuration and SHALL give that one instance to Mnemos, Empatheia, Hypnos and the evaluation sidecar. The default backend SHALL be a NumPy implementation of the configured sentence-transformers model that needs no torch, sentence-transformers or transformers, and that matches the sentence-transformers backend to 1e-5 per component with identical token ids. The storage dimension SHALL come from the model's configuration.

#### Scenario: A host without torch
- **WHEN** KAINE starts Mnemos with the default embedding backend where torch cannot be imported
- **THEN** Mnemos loads the model from its files on disk, encodes text, and the extras check does not require the `memory` extra for it

#### Scenario: The same vectors on either backend
- **WHEN** the same text is embedded by the NumPy and the sentence-transformers backends from the same model
- **THEN** the vectors agree to 1e-5 in every component

### Requirement: A memory store is bound to its embedding space
Every Mnemos store SHALL carry a stamp naming the embedding space its vectors belong to (model id, dimension, pooling and normalisation). Mnemos SHALL refuse to start on a store stamped with a different space than its embedder's, and SHALL never write vectors from two spaces into one store. A store with points but no stamp SHALL be treated as `sentence-transformers/all-MiniLM-L6-v2` when its dimension matches, stamped as such, and logged; otherwise Mnemos SHALL refuse it.

#### Scenario: A different model on an existing store
- **WHEN** Mnemos starts with an embedder whose space differs from the store's stamp
- **THEN** it fails to start with an error naming both spaces, and the store is unchanged

#### Scenario: A store from before stamping
- **WHEN** Mnemos starts on a 384-dimension store with points and no stamp, using MiniLM-L6-v2
- **THEN** it stamps the store as MiniLM-L6-v2, logs that it did, and starts
