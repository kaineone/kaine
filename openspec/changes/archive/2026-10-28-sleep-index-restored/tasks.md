## 1. Implementation

- [x] 1.1 Carry `sleep_index` in the sleep module's `serialize()` and restore it in `deserialize()`, keeping the larger value and ignoring malformed ones
- [x] 1.2 Raise the index to `stage.json`'s `sleep_count` in `initialize()` when that is larger, tolerating a missing or unreadable stage file
- [x] 1.3 Tests: round trip, malformed values, the stage restore feeding the next sleep's index, the larger record winning in both orders, and the corpus name format
- [x] 1.4 Document the restored index in docs/09-modules/sleep.md
