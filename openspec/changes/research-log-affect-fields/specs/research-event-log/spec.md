## ADDED Requirements

### Requirement: The research log carries the affect module's goal, emotion and regulation fields
The curated research log SHALL record, from the affect module's real payloads, `affect.goal` with `action`, `id`, `drive`, `reason`, `priority` and `likelihood`; `affect.emotion` with `state`, `coping_available`, `obstruction`, `goal_significance_method` and `reappraised` besides its earlier fields; `affect.state` with `reset` and `alert`; and `affect.regulation` with `tier`, `action`, `intensity`, `episode_s`, `size`, `bias`, `decay_s`, `emotion_before` and `emotion_after`. The regulation payload's `source` SHALL be recorded as `target_source`, and the record's `source` SHALL stay the publishing module. A goal's `description` SHALL NOT be recorded.

#### Scenario: A goal end keeps its id, drive and reason
- **WHEN** the affect module publishes `affect.goal` with `action` `abandoned`, `id` `g1`, `description` `relieve boredom`, `drive` `boredom` and `reason` `stalled`
- **THEN** the research record has `action`, `id`, `drive` and `reason` with those values and no `description`

#### Scenario: A tier-1 regulation event is logged
- **WHEN** the affect module publishes `affect.regulation` with `tier` 1 and `source` `vision`
- **THEN** a research record is written with `tier` 1, `target_source` `vision` and `source` `affect`

### Requirement: The broadcast record carries the regulation bias and the feedback gains
The research log's `workspace.broadcast` record SHALL copy the metadata's `regulation_bias` as `source` and `factor`, and its `workspace_feedback` as `arm`, `gains` and, for each episode, `kind`, `conflicting`, `toward`, `away` and `delta`. It SHALL NOT copy the feedback's `sequence_prediction`.

#### Scenario: Feedback metadata without the sequence prediction
- **WHEN** a broadcast's metadata carries `workspace_feedback` with `gains`, one conflict episode and a 24-element `sequence_prediction`
- **THEN** the record's `workspace_feedback` has the gains and the episode and no `sequence_prediction`

### Requirement: The sleep record carries the link and node pruning counts
The research log's `sleep.sleep.completed` record SHALL keep `memory_links_pruned` and `memory_nodes_pruned`.

#### Scenario: Link counts survive
- **WHEN** a sleep completes with `memory_links_pruned` 3 and `memory_nodes_pruned` 1
- **THEN** the research record has both counts
