## Why

Thymos's goal-significance check is dead. It scores the snapshot against a goal ledger by token overlap. Nothing in the running system adds a goal: `Thymos.add_goal` is called only from tests. So the ledger is always empty, relevance is 0.0, and the appraisal publishes `0.0 * 2.0 - 0.2 = -0.2` on every tick.

That constant is not neutral. It leans every appraisal toward goal obstruction, which shifts the categorical emotion mapping, and the `goal_significance_method` flag does not reveal that the value is constant. Thymos is on in base-thesis, so every base-thesis run so far carries this bias.

The entity does have concerns: its four Thymos drives (curiosity, boredom, social drive, restlessness), which build from its own state. The workspace already scores goal relevance against them. `DriveRelevanceGoalScorer` (from `2026-07-10-wire-salience-goal-thymos`) uses the drive-to-source table built from each module's `relieves_drives` declaration. In Scherer's component process model, the goal check is a check of relevance to the organism's needs and goals (Scherer 2009, the component process model the paper cites), and the drives are those needs.

## What Changes

- **Goal significance from the dominant drive.**
  - The appraisal scores the selected events against the entity's dominant drive with the same drive-to-source table the salience goal factor uses. The table is injected into Thymos by the boot wiring, so Thymos does not import the workspace.
  - With dominant drive value `v` and `f` the salience-weighted share of selected events whose source relieves that drive, `goal_significance = v × (2f − 1)`. Content that serves the pressing need is goal-conducive, and content that does not is obstructive, in proportion to how pressing the need is.
  - With no drive above zero, goal significance is 0.0.
- **Explicit goals still count when there are any.** When the ledger holds active goals, the score is the larger of the drive score and the ledger score. The ledger score is `relevance × 2 − 1`, so an unrelated goal reads as mild obstruction rather than a constant.
- **The constant −0.2 offset is removed.**
- **Honest disclosure.** `goal_significance_method` reports `drive_relevance_v1`, `drive_relevance_v1+token_overlap_v1` when active goals contributed, `token_overlap_v1` when no drive table was injected (unit construction) but active goals were scored, or `unavailable` when neither exists, with a score of 0.0.

## Capabilities

### Modified Capabilities

- `thymos`: the goal-significance appraisal check and its disclosure.

## Impact

- **Code:** `kaine/modules/thymos/module.py`; the boot wiring (`kaine/boot/wiring.py`, re-run on a Spot restart) hands Thymos the drive-to-source table the salience goal factor already uses. No `engine.py` change.
- **Preserved beings:** the goal ledger's serialized form is unchanged.
- **Research impact:** Thymos is on in base-thesis. The −0.2 bias disappears, and goal significance now varies with the entity's own drives, so the categorical emotion distribution changes. The next study is re-baselined with it. Past runs carried the constant; the record of this change says so.
- **Paper:** a revision note. The paper's appraisal description stays, and the note records that goal relevance is computed against the entity's homeostatic drives.
