## ADDED Requirements

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
