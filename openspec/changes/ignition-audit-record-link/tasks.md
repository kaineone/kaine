## 1. Implementation

- [x] 1.1 Link realizations through `record_links` in `classify_realizations`, keeping the last-intent link for requested sleeps only
- [x] 1.2 Build the record-id map from the two newest intent-log files in the sleep module, degrading to unlinked on a read failure
- [x] 1.3 Tests: each utterance maps to its own intent in any order, unlinked utterances count as self-initiated without an entry id, the planning and rest rules hold, and the module reads the links from a rotated corpus file and the live log
- [x] 1.4 Document the join in docs/09-modules/sleep.md
