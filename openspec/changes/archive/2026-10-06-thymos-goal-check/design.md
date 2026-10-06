## Context

- Prior work: `2026-05-20-thymos` built the appraisal; `2026-07-10-wire-salience-goal-thymos` built the drive-to-source table and `DriveRelevanceGoalScorer` for workspace salience.
- The salience goal factor ships on its static baseline pending validation. This change does not touch that flag.

## Decisions

### D1. Reuse the table, not the scorer

Thymos needs a signed score in `[-1, 1]`, while the salience factor is a multiplier in `[1 − attenuation, 1]`. The two therefore share the table and the dominant-drive rule (highest value, ties by name), not the class. The shared rule is extracted into one pure function in `kaine/workspace/strategies.py` that both call. Thymos receives it through the injected callable, not by import.

### D2. Emergence

The drives build from the entity's own state through existing Thymos dynamics. The source table comes from module declarations of what each faculty's events tend to relieve. Those declarations are an engineering mapping already used by salience and are not new here. No new hand-set emotion rule is added: the score is the existing CPM goal check fed by a real need signal instead of an empty ledger.

### D3. Ledger kept

The ledger API, its `thymos.goal` events and its preservation stay as they are. A future goal producer, such as Nous preferences or operator-given goals, plugs in through `add_goal`. Today nothing adds goals, and the method flag says so by omitting `token_overlap_v1`.
