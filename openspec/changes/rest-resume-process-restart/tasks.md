## 1. Implementation

- [x] 1.1 `update_state_cycle_entry`: replace only the sleep `state_cycle` entry in the existing checkpoint, with the entity check, the revive-record rule and the atomic encrypted write
- [x] 1.2 `ResumeCheckpointer` writes the entry at rest start, every 60 s of rest, at shutdown during a rest and at rest completion
- [x] 1.3 Sleep module accessor and boot wiring through the registry
- [x] 1.4 Tests: process restart with a fresh registry, crash mid-rest, crash after completion, other modules unchanged, encrypted tree, frozen time, other entity, revive record
- [x] 1.5 Docs: development.md resume checkpoint paragraph
