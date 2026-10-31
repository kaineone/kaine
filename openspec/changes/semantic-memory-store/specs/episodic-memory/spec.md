## ADDED Requirements

### Requirement: The semantic store ships off
`[episodic_memory.semantic].enabled` SHALL be false in the shipped configuration. With it false, or with associative replay off, no entry SHALL be written to the `semantic` collection and every sleep and recall SHALL behave as before this change. Enabling it with `recall_content` false SHALL promote entries but publish no semantic content.

#### Scenario: Off writes nothing
- **WHEN** a sleep runs with associative replay on and the semantic store off
- **THEN** the `semantic` collection is unchanged and phase 3's summary holds no promotion counts

### Requirement: Phase 3 promotes schema nodes that span several wakes
With the store and associative replay on, phase 3 SHALL call `promote_semantic()` after `associate()` and before `prune()`. Each schema node formed or changed in that sleep whose member traces span at least `min_wakes` distinct `born_sleep` values, default 3, and have members SHALL be promoted. Phase 3's summary SHALL report the counts of entries created, updated and skipped, and no text.

#### Scenario: A node from three wakes is promoted
- **WHEN** a changed schema node's center and partners were stored in three different wakes
- **THEN** the sleep creates or updates one semantic entry for it

#### Scenario: A node from one wake is not promoted
- **WHEN** every member trace of a changed node has the same `born_sleep`
- **THEN** no semantic entry is created for it

#### Scenario: Pruning still follows promotion
- **WHEN** `promote_semantic()` raises
- **THEN** `prune()` is still called and phase 3 reports the failure

### Requirement: An entry holds a gist and no episode
An entry SHALL hold, from its member traces' accessed members, each kind present in at least `min_share` of them (default 0.5) with its share and the median of each numeric felt field; the affect-tag mean; `own_words_share`; `n_episodes`, `n_wakes`, `first_sleep`, `last_sleep`; at most `max_members` member references (default 64); and the centroid embedding. It SHALL hold no trace text, tick, wall-clock time, single episode's entity time or own words.

#### Scenario: A recurring kind enters the gist
- **WHEN** a vision report is accessed in four of six member traces and an audition report in two
- **THEN** the gist lists the vision report with share two thirds and omits the audition report

#### Scenario: Own words stay out
- **WHEN** member traces hold the entity's thought "the light keeps changing"
- **THEN** the entry's payload contains no part of that text and its `own_words_share` counts those traces

### Requirement: Overlapping promotions update one entry
A promoted node whose centroid has cosine similarity of at least `sim_merge` (default 0.9) with an existing entry, or that shares at least half its member traces with one, SHALL update that entry by recomputing its gist over the union of members, bounded by `max_members` with the most recent kept. Otherwise a new entry SHALL be created.

#### Scenario: A second promotion updates the entry
- **WHEN** a node sharing four of its six traces with an existing entry is promoted
- **THEN** that entry's `n_episodes` and `last_sleep` grow and no new entry is created

### Requirement: Entries downscale, prune and are refreshed by promotion
An entry SHALL carry a strength on the module's log gain, start at 1, be protected in the sleep that created or updated it, be scaled in every other sleep by the factor for an unreplayed trace, and be pruned at the floor and for the storage budget as traces are.

#### Scenario: An entry not promoted again fades
- **WHEN** an entry is not updated for a sleep that stores new traces
- **THEN** its strength falls by that sleep's downscaling factor

### Requirement: Recall searches the semantic collection
With the store on, the live recall SHALL also search the `semantic` collection, ranked by strength times similarity with the other collections. When a semantic entry ranks best and `recall_content` is true, `content` SHALL carry `kind = "semantic"`, the gist's kinds with their shares and medians, the affect mean, `own_words_share` and the entry reference.

#### Scenario: A semantic entry supplies the content
- **WHEN** the best-ranked result of a recall is a semantic entry
- **THEN** the recall event's `content.kind` is `"semantic"` and it carries the entry's gist and no trace text

### Requirement: Semantic entries travel with the entity
Semantic entries SHALL be exported in preservation bundles, restored on revive, backed up and deleted by decommission with the other collections, and never merged between entities.

#### Scenario: Revive restores the entries
- **WHEN** an entity with semantic entries is preserved and revived
- **THEN** the revived store holds the same entries with their gists and strengths relative to the restored log gain
