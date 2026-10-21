## 1. Implementation

- [x] 1.1 Pass each sleep's trigger from its start site to the pipeline and drop the module-level fatigue flag
- [x] 1.2 Carry `trigger` on the started, completed and aborted completed events, and derive `fatigue_triggered` from it
- [x] 1.3 Keep `trigger` in the research log and name it in the faithful narration
- [x] 1.4 Tests: each start site records its own trigger, a fatigue sleep followed by a backstop sleep records `fatigue` then `backstop`, a losing double trigger leaves the running sleep's trigger alone, the aborted event carries the trigger, and the research log keeps it
- [x] 1.5 Document the trigger values in docs/09-modules/sleep.md, docs/10-sleep/README.md and docs/17-research-data/event-streams.md
