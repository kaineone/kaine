## 1. Implementation

- [x] 1.1 Score the drive term as `v × f` and the ledger term as `relevance`, both in `[0, 1]`, in the affect module's goal check
- [x] 1.2 Note in `classify()` and `docs/09-modules/affect.md` that anger is unreachable while the goal score cannot be negative
- [x] 1.3 Tests: unrelated content scores 0.0; an idle coalition with an unmet drive classifies as neutral, not anger; serving content still scores `v × f`
