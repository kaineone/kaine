# episodic memory Specification

## Purpose
The episodic memory module stores what KAINE experiences. This capability covers its KAINE-owned, authenticated Qdrant store and collections, the store and recall API with its shared text embedder, automatic storage of workspace broadcasts, consolidation from short-term to episodic memory, and spontaneous cue-based recall in the live loop.

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
The episodic memory module SHALL manage four memory stores with the build-prompt-prescribed
names: `short_term` (in-process buffer, not persisted), `episodic`,
`semantic`, and `procedural` (persisted in Qdrant). The collection
prefix `episodic_memory_` SHALL be configurable.

#### Scenario: Four collections exist after initialize
- **WHEN** `EpisodicMemory.initialize` completes against a fresh Qdrant
- **THEN** the three Qdrant collections `episodic_memory_episodic`,
  `episodic_memory_semantic`, `episodic_memory_procedural` exist and accept points

#### Scenario: Short-term is in-memory only
- **WHEN** the episodic memory module is shut down and reinitialized
- **THEN** the short-term buffer is empty (no Qdrant collection by
  that name exists)

### Requirement: Store and recall API
The episodic memory module SHALL expose `store(text, payload, affect=None, collection="short_term")` that attaches `payload` and `affect` metadata and writes to the named store. For `short_term` the text SHALL be stored without embedding; for the other collections it SHALL be embedded at store time. The episodic memory module SHALL expose `recall(query_text, k=5, collection="episodic")` that embeds the query, scores the named store's entries by cosine similarity to it, returns up to `k` matches as `RecalledMemory` dataclasses, and, for collections other than `short_term`, invokes the configured `EmotionalRetriggerHook` with the affect summary of those matches. For `short_term`, each entry's embedding SHALL be computed at most once per embedding space, held in memory only, and never exported or persisted; equal scores SHALL rank the more recent entry first.

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

### Requirement: Short-term consolidates into episodic at capacity
The episodic memory module SHALL evict the oldest short-term entry into the episodic
collection on the next `store` call whenever the short-term buffer is
at its configured capacity (default 128). The original payload,
affect, and timestamp SHALL be preserved across the move.

#### Scenario: 129th store evicts oldest to episodic
- **WHEN** short-term capacity is 128 and the 129th `store` call
  arrives
- **THEN** the oldest of the 128 prior entries is moved into the
  episodic collection and the short-term buffer's size is 128

### Requirement: Workspace broadcasts auto-store into short-term
The episodic memory module SHALL produce exactly one `store` call into the short-term buffer for every `workspace.broadcast` it observes through its base module workspace consumer. The stored text SHALL be a deterministic serialization of the snapshot's selected events, naming each event's source and type with its payload after the privacy filter's vector rule has removed every vector field and every numeric list of 16 or more items. The serialization SHALL NOT include the tick index or bus entry IDs; the tick index is kept in the stored payload.

#### Scenario: One broadcast in produces one short-term entry
- **WHEN** the episodic memory module receives one workspace broadcast through its base module consumer with two selected events
- **THEN** the short-term buffer's size increases by exactly 1

#### Scenario: A foveated vision report stores no vectors
- **WHEN** the selected events include a `vision.report` carrying `peripheral`, `foveal` and `latent` vectors
- **THEN** the stored text contains none of those vectors' values and still names `vision:vision.report`

### Requirement: Diagnostics-only bus event for recall
Each `recall` call SHALL publish a `episodic_memory.recall` event to `episodic_memory.out`
containing `count`, `collection`, `query_length`, and the maximum
affect intensity among the returned memories — but SHALL NOT include
the memory contents or the raw query text. The privacy boundary from
build prompt §8.3 applies here even pre-dashboard.

#### Scenario: Recall publishes count without contents
- **WHEN** `recall(query, k=5)` returns 3 matched memories
- **THEN** the published `episodic_memory.recall` event has `count == 3` and
  no fields containing the memory texts or the query string

### Requirement: Default Episodic memory config and disabled-by-default
The repository SHALL ship a `[episodic_memory]` block in `config/kaine.toml`
with default values for `backend` (`qdrant`), `collection_prefix`,
`short_term_capacity`, `recall_top_k`, `baseline_salience` and
`alert_salience`, and an `[embedding]` block with `backend` (`numpy`),
`model_id` and `device`. `[episodic_memory]` SHALL NOT accept `embedder_model_id`
or `device`: boot SHALL reject either with an error naming the
`[embedding]` key that replaces it. The `[modules].episodic_memory = false` flag
SHALL keep first boot from auto-registering the episodic memory module.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[episodic_memory]` section with the documented keys, an `[embedding]` section, and `[modules].episodic_memory == false`

#### Scenario: The old embedder keys are refused
- **WHEN** an operator config sets `[episodic_memory].embedder_model_id` or `[episodic_memory].device`
- **THEN** boot fails with an error naming `[embedding].model_id` or `[embedding].device`

### Requirement: Spontaneous cue-based recall in the live loop

The episodic memory module SHALL perform cue-based recall in the live loop: on an experiential
workspace broadcast that carries a meaningful cue, it derives a query from the
conscious snapshot, calls `recall()`, and publishes the recalled memories as
`episodic_memory.recall` events, so recalled context re-enters the workspace and reaches
downstream consumers (e.g. the affect module). Recall SHALL occur before the snapshot is
stored for that tick
(so the cue retrieves prior memories, not the just-stored one). Recall SHALL be
throttled by a cooldown so it does not fire on every tick, and SHALL be skipped
when there is no meaningful cue. Recall SHALL run regardless of
`snapshot.inhibited` (recall is internal cognition, not an outward action).
Storing the snapshot each experiential tick SHALL continue unchanged.

#### Scenario: A cued experiential tick triggers recall

- **WHEN** an experiential broadcast with a non-empty cue occurs and the recall
  cooldown has elapsed
- **THEN** the episodic memory module calls recall and publishes a `episodic_memory.recall` event

#### Scenario: Cooldown suppresses repeated recall

- **WHEN** experiential broadcasts occur faster than the recall cooldown
- **THEN** the episodic memory module recalls at most once per cooldown window

#### Scenario: No cue, no recall

- **WHEN** a broadcast carries no meaningful cue
- **THEN** the episodic memory module performs no recall

#### Scenario: Recall is not inhibition-gated

- **WHEN** a cued experiential broadcast is inhibited and the cooldown elapsed
- **THEN** the episodic memory module still performs recall (recall is cognition, not action)

#### Scenario: Storing still happens every experiential tick

- **WHEN** an experiential broadcast occurs
- **THEN** the episodic memory module stores the snapshot as before, independent of whether recall
  fired

### Requirement: Episodic memory recall does not fabricate empty success on storage failure

`QdrantStorage.search()` SHALL raise `StorageError` (not return `[]`) when
the Qdrant backend operation fails.  `EpisodicMemory.recall()` SHALL catch
`StorageError`, log it at `error` level, and publish a `episodic_memory.recall` event
carrying `"error": true` and `"error_detail"` — never a fake `count=0` result
that looks like a successful empty search.

`InMemoryStorage.search()` is unaffected: missing collections return `[]`
normally (that is a valid empty result, not a storage failure).

#### Scenario: Qdrant backend failure

- **WHEN** `QdrantStorage.search()` encounters any exception from the client
- **THEN** it raises `StorageError` with a descriptive message
- **AND** does NOT return `[]`

#### Scenario: Episodic memory recall on StorageError

- **WHEN** `EpisodicMemory.recall()` encounters a `StorageError`
- **THEN** it logs the error at `logging.ERROR` level
- **AND** publishes `episodic_memory.recall` with `"error": true`
- **AND** returns `[]` to the caller (graceful empty, not a fake success)
- **AND** the published event does NOT carry `"error": true` on a successful recall

#### Scenario: Successful recall

- **WHEN** `EpisodicMemory.recall()` completes without error
- **THEN** `episodic_memory.recall` is published with real `count` and no `"error"` key

### Requirement: One shared text embedder with a torch-free default
KAINE SHALL build a single text embedder per registry from the `[embedding]` configuration and SHALL give that one instance to the episodic memory module, the social cognition module, the sleep module and the evaluation sidecar. The default backend SHALL be a NumPy implementation of the configured sentence-transformers model that needs no torch, sentence-transformers or transformers, and that matches the sentence-transformers backend to 1e-5 per component with identical token ids. The storage dimension SHALL come from the model's configuration.

#### Scenario: A host without torch
- **WHEN** KAINE starts the episodic memory module with the default embedding backend where torch cannot be imported
- **THEN** the episodic memory module loads the model from its files on disk, encodes text, and the extras check does not require the `memory` extra for it

#### Scenario: The same vectors on either backend
- **WHEN** the same text is embedded by the NumPy and the sentence-transformers backends from the same model
- **THEN** the vectors agree to 1e-5 in every component

### Requirement: A memory store is bound to its embedding space
Every episodic memory store SHALL carry a stamp naming the embedding space its vectors belong to (model id, dimension, pooling and normalisation). The episodic memory module SHALL refuse to start on a store stamped with a different space than its embedder's, and SHALL never write vectors from two spaces into one store. A store with points but no stamp SHALL be treated as `sentence-transformers/all-MiniLM-L6-v2` when its dimension matches, stamped as such, and logged; otherwise the episodic memory module SHALL refuse it.

#### Scenario: A different model on an existing store
- **WHEN** the episodic memory module starts with an embedder whose space differs from the store's stamp
- **THEN** it fails to start with an error naming both spaces, and the store is unchanged

#### Scenario: A store from before stamping
- **WHEN** the episodic memory module starts on a 384-dimension store with points and no stamp, using MiniLM-L6-v2
- **THEN** it stamps the store as MiniLM-L6-v2, logs that it did, and starts

### Requirement: Recent points rank a non-finite timestamp as zero
`MemoryStorage.recent_points()` SHALL rank a point whose payload timestamp is
missing, unparseable, NaN or infinite as if its timestamp were 0.0, on the
in-memory, sqlite-vec and Qdrant backends alike.

#### Scenario: Non-finite timestamps rank as the oldest
- **WHEN** a collection holds points with finite positive timestamps and
  points with NaN, positive infinite and negative infinite timestamps
- **THEN** `recent_points()` returns the finite points first, newest first,
  on every backend

### Requirement: Associative replay co-replays related traces of different periods
After a sleep's downscaling, the episodic memory module's `associate()` SHALL co-replay at most `n_pair` pairs (paper A.10, Table A1: `n_pair = 5`, `sim_min = 0.5`, `sim_dup = 0.95`). Each pair SHALL join a persisted trace of the replayed set `Q` with a persisted trace stored before the wake window `W` (its `born_sleep` is below the sleep index the downscaling counted as `W`), whose cosine similarity `sim` satisfies `sim_min <= sim < sim_dup`. The pairs SHALL be taken most similar first across all of `Q`. A trace of `W` SHALL never be the older member, and a short-term entry SHALL never be a member. `associate()` SHALL report each co-replayed pair's two point ids and its new weight, and no text.

#### Scenario: A related older trace is linked
- **WHEN** `Q` holds a trace whose embedding has cosine 0.8 with a trace stored in an earlier wake
- **THEN** `associate()` reports that pair with weight 0.5

#### Scenario: Near-duplicates and unrelated traces are not linked
- **WHEN** the only older traces have cosine 0.97 and 0.3 with every trace of `Q`
- **THEN** `associate()` reports no pair and stores no link

#### Scenario: Traces of the same wake are not linked
- **WHEN** a trace of `Q` has cosine 0.8 only with another trace stored in the same wake
- **THEN** `associate()` reports no pair

#### Scenario: At most n_pair pairs, most similar first
- **WHEN** seven older traces lie in the band with a trace of `Q`
- **THEN** `associate()` reports the five with the highest similarity, in decreasing order of similarity

### Requirement: Link weights follow co-replay and downscaling
A link's weight `w` SHALL be 0 before its first co-replay, and each co-replay SHALL set it to `(1 + w) / 2`. The link SHALL be stored with a `log_base` on the same log gain as trace strengths, so that a downscaling multiplies `w` by the factor that multiplies an unreplayed trace's strength `h_i`. The weight SHALL never exceed 1.

#### Scenario: A second co-replay halves the remaining distance
- **WHEN** a pair is co-replayed in two consecutive sleeps whose downscalings stored no traces
- **THEN** its weight is 0.5 after the first and 0.75 after the second

#### Scenario: Downscaling scales a link like a trace
- **WHEN** a sleep downscales by the factor `f` and does not co-replay a linked pair of weight `w`
- **THEN** the link's weight afterwards is `f * w`

### Requirement: Each trace keeps at most n_link links
After the co-replays of a sleep, every trace with more than `n_link` links (Table A1: 8) SHALL lose its weakest links, lower weight first and older co-replay first among equals, until it has `n_link`.

#### Scenario: The weakest link goes first
- **WHEN** a co-replay gives a trace its ninth link and `n_link` is 8
- **THEN** the trace's weakest link is deleted and the trace keeps eight

### Requirement: A trace with at least n_sch links forms a schema node
When a sleep changes the links of a trace that then has at least `n_sch` links (Table A1: 3), the module SHALL store a schema node for it whose embedding is the mean of the trace's and its partners' embeddings and whose strength is the mean weight of the trace's links, stored as a `log_base` on the same log gain. When the trace has fewer than `n_sch` links, or is deleted, its node SHALL be deleted.

#### Scenario: The third link forms a node
- **WHEN** a trace gains its third link
- **THEN** a schema node exists whose embedding is the centroid of the four embeddings and whose strength is the mean of the three link weights

#### Scenario: Losing a link below n_sch removes the node
- **WHEN** a trace with a schema node and three links loses one
- **THEN** its schema node is deleted

### Requirement: Recall returns linked partners and matches schema nodes
`recall()` on a persisted collection SHALL rank the schema nodes whose trace belongs to that collection together with its traces, by strength times cosine similarity with the cue, and return the `k` best with similarity above 0. A returned schema node SHALL carry the text of its trace, `schema_node: true` and its member ids in its payload. After the ranked results, recall SHALL also return each returned trace's link partners that are not already returned, in decreasing order of link weight. Recall SHALL change no strength and no weight.

#### Scenario: Recall of one member returns the other
- **WHEN** traces A and B are linked and a cue similar only to A recalls with `k = 1`
- **THEN** the results hold A first and then B

#### Scenario: Recall matches a schema node
- **WHEN** a cue lies closest to a schema node's centroid and the node's strength times similarity is the highest
- **THEN** the node is the first result, with `schema_node: true` in its payload

### Requirement: Links and nodes count in the store size and are pruned as traces are
Link and node records SHALL count in the store size `S` that the budget `B` bounds. Pruning SHALL run after associative replay in the sleep that co-replays: it SHALL delete every trace, link and node whose strength or weight is below the floor `h_min`, then, while `S > B`, the weakest record outside `Q` among traces, links and nodes, oldest first among equals. A deleted trace SHALL take its links with it, and the nodes of its partners SHALL be recomputed or deleted. Total trace strength SHALL count traces only.

#### Scenario: A deleted trace takes its links
- **WHEN** pruning deletes a linked trace at the floor
- **THEN** its links are deleted in the same pruning and `S` falls by their sizes too

#### Scenario: A link below the floor is pruned
- **WHEN** downscalings bring a link's weight below `h_min`
- **THEN** the next pruning deletes the link and keeps both traces

#### Scenario: Link records count toward the budget
- **WHEN** traces and links together exceed the budget
- **THEN** pruning deletes the weakest records until `S <= B`, and the reported store bytes include the link and node records

### Requirement: Links and nodes persist through preservation and revive
Links and schema nodes SHALL be stored in the persisted collections `<prefix>links` and `<prefix>schemas`, created on the first co-replay, holding vectors of the store's embedding space under its stamp. `export_state()` SHALL include them and `import_state()` SHALL restore them with the trace collections, so that a revived entity has the same links, weights and nodes relative to its restored log gain. Decommission SHALL back up and delete them with the trace collections.

#### Scenario: Links survive a revive
- **WHEN** a store with links and a schema node is exported and imported into a fresh store
- **THEN** recall of a member returns its partner and every link weight and node strength equals its value before the export

#### Scenario: A store without associations exports as before
- **WHEN** a store has never co-replayed a pair
- **THEN** no association collection exists and `export_state()` holds only the trace collections

### Requirement: Persisted traces carry a strength
Each trace in the episodic memory module's persisted collections SHALL carry a strength
$h_i\in(0,1]$, stored as `log_base` in its payload with
$h_i=\exp(\texttt{log\_base}_i+L)$, where $L$ is the store's log gain kept in
a meta record beside the embedding-space stamp with the sleep count, the total
strength and the entity time of the last sleep. A trace SHALL be persisted at
strength 1 with `born_sleep` set to the current sleep count and `entity_time`
set to its storage time on the entity clock. `entity_time` SHALL continue
across restarts. A caller's payload SHALL NOT set `log_base`, `born_sleep` or
`entity_time`. `payload["timestamp"]` SHALL stay wall-clock time. A trace is
below the floor when $h_i<h_{\min}$; no such trace SHALL exist while the entity is awake.

#### Scenario: A persisted trace starts at full strength
- **WHEN** a trace is persisted
- **THEN** its strength is 1, its `born_sleep` is the current sleep count, it
  carries an `entity_time`, and reserved keys in the caller's payload are
  ignored

#### Scenario: Storage times continue across a restart
- **WHEN** the episodic memory module restarts in the middle of a wake and stores another trace
- **THEN** that trace's `entity_time` is later than every trace stored earlier
  in the same wake

### Requirement: Sleep downscales strengths and protects replayed traces
`EpisodicMemoryCore.downscale(protect)` SHALL count $N_{\rm new}$, the persisted traces
with `born_sleep` equal to the sleep count, and SHALL multiply the strength of
every persisted trace outside `protect` by
$\varrho^{N_{\rm new}/N_{\rm day}}$, where $\varrho$ is
`[episodic_memory.strength].retention_per_day` and $N_{\rm day}$ is
`[episodic_memory.strength].traces_per_day`, default 288,000 (86400 x f0 with the
paper's f0 = 10/3). The traces in `protect` SHALL keep
their strength. It SHALL NOT change any vector. It SHALL write the new meta
before it writes the protected traces, so a crash between the two can only
remove strength. It SHALL return `n_new`, `factor`, `protected`,
`total_before`, `total_after`, `pruned_floor`, `pruned_budget` and
`store_bytes`.

#### Scenario: One day of storage keeps the retention fraction
- **WHEN** $N_{\rm day}$ traces were stored since the last sleep and nothing is
  replayed
- **THEN** every older trace keeps the fraction $\varrho$ of its strength

#### Scenario: A sleep after an empty wake changes nothing
- **WHEN** no trace was stored since the last sleep
- **THEN** the factor is 1 and no strength changes

#### Scenario: Protected traces keep their strength
- **WHEN** a sleep protects some traces
- **THEN** their strengths are unchanged, the ratios among the other traces are
  unchanged, and the total strength falls

### Requirement: Recall ranks by strength times similarity
Recall from a persisted collection SHALL return the requested number of
traces with cosine similarity above 0, in decreasing order of
strength times similarity, exactly relative to the backend's cosine order, and
SHALL change no strength. Each result SHALL report `similarity`, `strength`
and `score`, the product. Short-term traces SHALL rank by similarity alone.
On sqlite-vec the search SHALL filter by collection inside the vector index
and SHALL page past the extension's limit of 4096 rows.

#### Scenario: The stronger of two equally similar traces ranks first
- **WHEN** two traces have the same similarity to a cue and different strengths
- **THEN** the stronger one ranks first

#### Scenario: Top-k matches brute force
- **WHEN** recall runs on any backend
- **THEN** the results equal a brute-force ranking by strength times similarity

#### Scenario: sqlite-vec with other collections and more than 4096 rows
- **WHEN** other collections hold rows nearer the cue and the target collection
  needs more than 4096 rows to be searched
- **THEN** recall still returns the requested number of traces from the target
  collection, in the right order

### Requirement: Sleep prunes at the floor and to the storage budget
After the downscaling, in the same call, the episodic memory module SHALL delete every persisted
trace with $h_i<h_{\min}$ (`[episodic_memory.strength].prune_floor`), and then, while
the stores' size $S$ exceeds `[episodic_memory].storage_budget_bytes`, the trace outside
the protected set with the lowest strength, the oldest by `entity_time` first
among equal strengths, stopping when $S$ fits or only protected traces remain.
$S$ SHALL be the sum over persisted traces of `size_bytes`, the record's
float32 embedding plus its serialized text, payload and affect, kept in the
meta record. No trace SHALL be deleted at any other time. The sleep summary
SHALL carry `memory_pruned_floor`, `memory_pruned_budget` and
`memory_store_bytes`, and the research log SHALL keep them.

#### Scenario: A trace below the floor is pruned in the sleep that weakened it
- **WHEN** a downscaling takes a trace below the floor
- **THEN** that trace is deleted in the same sleep and no remaining trace is
  below the floor

#### Scenario: The budget prunes the weakest, oldest first
- **WHEN** the stores exceed the budget after a sleep's downscaling
- **THEN** the weakest traces are deleted, the oldest first among equal
  strengths, until the stores fit

#### Scenario: Replayed traces are exempt
- **WHEN** the budget is smaller than the replayed traces alone
- **THEN** every other trace is deleted and the replayed ones remain

#### Scenario: Nothing is deleted while awake
- **WHEN** the stores exceed the budget between two sleeps
- **THEN** no trace is deleted until the next sleep

#### Scenario: A preserved bundle is unaffected by later pruning
- **WHEN** a store is captured and then pruned
- **THEN** the captured bundle still holds every trace and restores them

### Requirement: Store size and imports stay consistent with what is stored
The episodic memory module SHALL recompute the stores' size from a scan at initialize and at the
start of every downscaling, and SHALL change it, the total strength and the
pruned counts only after a deletion has succeeded, writing the meta after each
successful deletion. A preservation import SHALL mark the meta as pending
before it replaces any collection and clear the mark only when the imported
meta is written; while the mark is set, downscaling SHALL refuse to run and
initialize SHALL log an error. A strength SHALL be `exp(min(0, log_base + L))`,
and a non-finite sum SHALL be a storage error.

#### Scenario: A failed deletion does not cause over-pruning
- **WHEN** a deletion fails part way through pruning, or the process stops
  there, and the episodic memory module is started again
- **THEN** the stored size equals a scan and the next sleep prunes only what
  the budget requires

#### Scenario: An interrupted import blocks sleep
- **WHEN** an import fails after it began replacing collections
- **THEN** every later sleep is blocked and counted in the sleep summary and
  on the dashboard health board until a later import succeeds or the operator
  runs `python -m kaine.lifecycle.episodic_memory_recover --confirm-keep-current-store`

#### Scenario: Disk growth stays bounded while blocked
- **WHEN** an import is pending and the stores exceed twice the budget
- **THEN** new traces are refused, each refusal is logged and counted, and no
  welfare event is raised

### Requirement: Strength survives migration and preservation
At initialize the episodic memory module SHALL backfill, idempotently, every persisted point
without `log_base` to strength 1 with `born_sleep = -1`, and SHALL write a
missing meta before the backfill. It SHALL refuse a store without the meta
whose points already carry `log_base`. A preservation capture SHALL carry the
meta, and a restore SHALL write it after the collections. A restore of a bundle
without the meta and without `log_base` SHALL backfill it, and a restore of a
bundle without the meta whose points carry `log_base` SHALL fail. Decommission
SHALL delete the meta with the embedding-space stamp.

#### Scenario: A legacy store is migrated once
- **WHEN** a store from before this change is initialized twice
- **THEN** every trace has strength 1 after the first initialize and the second
  changes nothing

#### Scenario: Preservation round trip keeps strengths
- **WHEN** a store with downscaled traces is exported and imported
- **THEN** every trace has the same strength and the meta is the same
