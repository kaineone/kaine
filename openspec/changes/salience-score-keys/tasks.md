## 1. Implementation

- [x] 1.1 A failing test: two candidates from different streams with one entry id lose a score
- [x] 1.2 `stream_entry_key` and `split_stream_entry_key` in `kaine.bus.schema`
- [x] 1.3 The cycle gathers stream-qualified candidate ids and keeps the paper's within-tick order
- [x] 1.4 Syneidesis refuses duplicate candidate ids in every arm
- [x] 1.5 Tests: each arm's table has one key per candidate and every member's id is a key; `BroadcastContext` reads each member's own score; key helpers accept the bare legacy form
- [x] 1.6 Docs: the candidate key in the cycle, workspace and research-data pages
