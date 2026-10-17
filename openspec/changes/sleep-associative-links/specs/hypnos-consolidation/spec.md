## REMOVED Requirements

### Requirement: Phase-3 associative replay with World model scenarios
**Reason**: The paper (A.10, *Associative replay*) defines phase 3 as co-replay of related trace pairs that are recorded as weighted links; it keeps no world-model scenario cue and no selection by time period.
**Migration**: Phase 3 calls the episodic memory module's `associate()` and `prune()`; `sleep.association` carries a pair's point ids and weight.

## ADDED Requirements

### Requirement: Phase-3 associative replay links related traces
When `[sleep.consolidation].associative_replay` is true, phase 2 SHALL downscale without pruning, and phase 3 SHALL call the episodic memory module's `associate()` and then its `prune()`, the latter also when `associate()` fails. Phase 3 SHALL publish one `sleep.association` event per co-replayed pair carrying only the pair's two point ids (`a`, `b`) and its new weight (`weight`). Phase 3 SHALL NOT cue the world model module. When the flag is false, phase 3 SHALL be a successful no-op and phase 2 SHALL call `downscale` exactly as before, which prunes.

#### Scenario: Phase 3 off leaves phase 2 unchanged
- **WHEN** a sleep runs with `associative_replay = false`
- **THEN** phase 2 calls `downscale(protect=...)` with no other argument and phase 3 reports that the flag is not enabled

#### Scenario: Phase 3 on links and then prunes
- **WHEN** a sleep runs with `associative_replay = true`
- **THEN** phase 2 calls `downscale(protect=..., prune=False)`, phase 3 calls `associate()` then `prune()`, and one `sleep.association` event with `a`, `b` and `weight` and no text is published per reported pair

#### Scenario: Pruning runs when association fails
- **WHEN** `associate()` raises during phase 3
- **THEN** `prune()` is still called and phase 3 reports failure
