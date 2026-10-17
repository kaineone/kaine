## Why

The curated research log copies only the payload keys its taxonomy names, and the affect changes #515 to #519 added fields the taxonomy never learned. In the 2026-10-16 integration boot the decrypted `affect.goal` records kept only `action`: the allowlist names `goal_id` while the affect module publishes `id`, and it lists neither `reason`, `drive`, `priority` nor `likelihood`. `affect.emotion` records lost `coping_available`, `obstruction`, `goal_significance_method` and `reappraised`. `affect.regulation` is not in the taxonomy, so no regulation activation was ever logged. The broadcast record drops the `regulation_bias` and `workspace_feedback` metadata, and `sleep.sleep.completed` drops the link and node pruning counts that associative replay added. The paper's studies read "a content-free research log of rates and drives" (§6.2), and the workspace-feedback change (task 3.1) needs the gains and conflict episodes in the log for the §6.4 stability measures.

## What Changes

- `affect.goal`: allowlist `action`, `id`, `drive`, `reason`, `priority` and `likelihood`. The never-published `goal_id` is removed. The goal's `description` stays excluded: it is free text (operator-added goals carry arbitrary text) and is already in `CONTENT_FIELDS`.
- `affect.emotion`: add `state`, `coping_available`, `obstruction`, `goal_significance_method` and `reappraised`.
- `affect.state`: add `reset` and `alert`, so the affective reset is visible in the log.
- `affect.regulation` joins the taxonomy with `tier`, `action`, `intensity`, `episode_s`, `size`, `bias`, `decay_s`, `emotion_before` and `emotion_after`. Its payload `source` (the module whose scores tier 1 biases) is recorded as `target_source`, so it never overwrites the record's own `source`.
- The broadcast record copies `regulation_bias` (`source`, `factor`) and `workspace_feedback` (`arm`, `gains` and each episode's `kind`, `conflicting`, `toward`, `away` and `delta`). The feedback's `sequence_prediction` stays excluded: it is the sequence module's predicted 24-dimensional feature vector, latent content the log already excludes from `sequence.report`.
- `sleep.sleep.completed`: add `memory_links_pruned` and `memory_nodes_pruned`.
- `vision.report` and `audition.perception`: add `normalised_change`, the change ratio a parallel change (arousal-change-excess) starts publishing; while it is absent the key is simply not copied.
- `kaine/experiment/log_schema.py` declares ranges for the new bounded numeric fields.
- The per-pair `sleep.association` events stay out of the log: the paper names no analysis that reads them, and the sleep's pruning counts carry the link totals.

## Capabilities

### Modified Capabilities

- `research-event-log`: the log carries the affect, regulation, feedback and link fields.

## Impact

- `kaine/evaluation/observers/research_event_observer.py`, `kaine/experiment/log_schema.py`, `tests/test_research_event_log.py`, `docs/17-research-data/event-streams.md`, `openspec/changes/workspace-feedback/tasks.md` (task 3.1).
- Every new field is a number, a flag, a fixed code or an opaque id. Records written before this change lack the fields.
