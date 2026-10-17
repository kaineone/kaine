## 1. Implementation

- [ ] 1.1 Taxonomy: affect.goal, affect.emotion, affect.state, the new affect.regulation with `target_source`, and the sleep.sleep.completed link counts
- [ ] 1.2 Broadcast record: regulation_bias and workspace_feedback without sequence_prediction
- [ ] 1.3 log_schema ranges for the new bounded fields
- [ ] 1.4 Tests: a round trip of each real producer payload keeps every allowed key and drops the excluded ones
- [ ] 1.5 Docs: docs/17-research-data/event-streams.md

## 2. Verification

- [ ] 2.1 Mutation checks on the allowlists and the source rename
- [ ] 2.2 Worker first-pass review and fixes
