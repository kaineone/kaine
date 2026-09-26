## 1. Implementation

- [x] 1.1 `kaine/cycle/programme_end.py`: `ProgrammeEndWatcher` (end detection, one request, result wait, freeze and notify on failure, once per start).
- [x] 1.2 Wiring in the cycle entrypoint when a shared playlist clock exists; cancelled at shutdown.
- [x] 1.3 `docs/operations.md`: what happens at the end of a playlist.

## 2. Verification

- [x] 2.1 Tests: no action before the end, while paused at or past the end, or before the clock starts; exactly one request at the end, with reason `programme end` and stop set; an `ok` result ends the watcher with no freeze; an `ok: false` result or a timeout freezes under `programme_end`, logs CRITICAL and notifies; a second end in the same start is ignored.
- [x] 2.2 Offline suite green; `openspec validate film-end-preserve --strict`.
