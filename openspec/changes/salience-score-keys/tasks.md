## 1. Implementation

- [x] 1.1 A failing test: two candidates from different streams with one entry id lose a score
- [x] 1.2 `stream_entry_key` and `split_stream_entry_key` in `kaine.bus.schema`
- [x] 1.3 The cycle gathers stream-qualified candidate ids and keeps the paper's within-tick order
- [x] 1.4 The workspace refuses duplicate candidate ids in every arm
- [x] 1.5 Tests: each arm's table has one key per candidate and every member's id is a key; `BroadcastContext` reads each member's own score; key helpers accept the bare legacy form
- [x] 1.6 Docs: the candidate key in the cycle, workspace and research-data pages

## 2. Coordinator follow-ups

- [x] 2.1 The canonical sort compares bus entry ids as (ms, seq); a test with twelve entries in one millisecond
- [x] 2.2 After #478 merges: the research log records the stream-qualified id for tone events, the tone analysis joins on it, and a test finds a tone event accessed through the engine path

## 3. Second-review items

- [x] 3.1 The bare-id refusal names a pre-upgrade record; the docs describe it and that bare ids are never coerced
- [x] 3.2 The proposal notes that earlier runs are not reproduced bit for bit where same-source ids differ in digit count
- [x] 3.3 Tests: the matched draw is the same for one seed over the new order; read cursors stay raw bus ids
