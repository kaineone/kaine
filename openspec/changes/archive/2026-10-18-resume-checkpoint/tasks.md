## 1. Implementation

- [x] 1.1 Add `kaine/lifecycle/resume_checkpoint.py`: capture, encrypted atomic write, read, identity-checked restore without revive side effects, the self-persisting module and bus-cursor exclusions, and the periodic checkpointer driven by awake entity time
- [x] 1.2 Wire it into the cycle: restore on a plain start after module initialisation, replace the checkpoint once a revive lands, start the checkpointer in a new `_phase_checkpoint`, write once at a clean shutdown unless asleep
- [x] 1.3 Decommission backs up and deletes `state/lifecycle/checkpoint`
- [x] 1.4 Docs: development progress across restarts, preservation and revive, the module-addition study's resume

## 2. Tests

- [x] 2.1 Restart round trip with real modules (self-rhythm log recovery time, affect drives and outcome counts, goal ledger) restores identical state
- [x] 2.2 Missing, corrupt, undecryptable and other-entity checkpoints are ignored; absent and disabled modules are handled
- [x] 2.3 Exactly one checkpoint after many writes; encrypted when encryption is configured; no periodic write while frozen or asleep; shutdown writes one
- [x] 2.4 A revive wins over a stale checkpoint; decommission backs up and deletes the checkpoint
- [x] 2.5 Mutation-check the key tests and run the full suite
