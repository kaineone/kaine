## 1. Goal significance

- [ ] 1.1 Extract the dominant-drive rule into a pure helper in `kaine/workspace/strategies.py`, used by `DriveRelevanceGoalScorer` (behaviour unchanged, existing tests green).
- [ ] 1.2 `Thymos.set_drive_relevance(table)` stores the table. The appraisal computes `v × (2f − 1)` from Thymos's own drives, combined with the ledger score (`relevance × 2 − 1`) by max when active goals exist. The −0.2 offset is removed.
- [ ] 1.3 `kaine/cycle/__main__.py` passes `drive_sources_for(registry)` to Thymos when Thymos is enabled.
- [ ] 1.4 `goal_significance_method` reports `drive_relevance_v1`, `drive_relevance_v1+token_overlap_v1` or `unavailable`.
- [ ] 1.5 Tests:
  - high social drive with Audition events selected gives positive significance;
  - high social drive with only Soma events gives negative significance;
  - all drives at zero give 0.0;
  - an active matching goal raises the score;
  - no table gives 0.0 and `unavailable`;
  - a cycle-assembly test checks that Thymos receives the table.

  Mutation-check each one.

## 2. Paper and docs

- [ ] 2.1 Revision note in the paper repository's `REVISION-NOTES.md`.
- [ ] 2.2 `docs/09-modules/thymos.md` describes the goal check.
- [ ] 2.3 `openspec validate thymos-goal-check --strict`.
