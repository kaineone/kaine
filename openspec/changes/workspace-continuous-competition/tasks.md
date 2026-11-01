## 0. Before code

- [ ] 0.1 Capture the golden digest for the absence test (task 6.1) from the commit before this change's first code commit, with the deterministic engine run at the shipped configuration; commit it with the test.

## 1. Candidate pool

- [ ] 1.1 `kaine/cycle/candidate_pool.py`: report keys and protected keys; replace on arrival; consume accessed members after a published broadcast; stale rule for declared periodic types (running mean of the last eight intervals, nominal period until two) and `event_hold_s` for event-driven types; protected members leave only on access or replacement and keep `pending_since` across replacement; unpaused entity time from `CycleEngine.paused_subjective_seconds`; per-minute content-free summary. `[workspace.pool]` parses `enabled`, `capacity`, `stale_tolerance`, `event_hold_s`, `priority_wait_s` and refuses unknown keys; the `[workspace]` key guard accepts the subtable. Tests in `tests/test_candidate_pool.py`: supersede, consume, inhibited consumes nothing, failed publish consumes nothing, stale periodic, event-driven hold, protected never stale, replacement keeps the pending time, access closes the episode, a freeze ages nothing, no event is created or copied (identity check on held objects), the pool is not in the checkpoint or a bundle.
- [ ] 1.2 `PERIODIC_REPORT_TYPES` with nominal periods (vision, audition perception and emotion, interoception, affect state, sequence report) and `PROTECTED_REPORT_TYPES` (affect: `affect.drive` keyed by `drive` over the four drives; interoception: alarm report, fatigue, regulation); boot refuses a bad period; `N_p` recorded in the run manifest. Tests over the registry, including that every drive in `DriveSet` is declared and that classification reads no payload field but `alert` and the key field.
- [ ] 1.3 The citations and design-choice labels of design D2, D3 and D5 at the code sites.

## 2. Engine

- [ ] 2.1 `CycleEngine.tick`: arrivals go to `_forward_own_output`, the affect observer, `_update_access_rate` and the feedback head; the pool goes to `select` and `select_dual`; consumption after a published broadcast. Tests in `tests/test_engine_candidate_pool.py`: a report published on a non-broadcast tick competes on the next broadcast tick; a held alert raises the phasic input once; a held `affect.state` is observed once; the arousal read by the access rate holds when nothing arrives.
- [ ] 2.2 Live bound check and `workspace.pool.defect` with the caretaker notice. Test with a selection fault injected.
- [ ] 2.3 Boot conditions: competitive arm only, capacity at least 1, finite positive tolerances, the never-persisted bus rule in force. Tests for each refusal.
- [ ] 2.4 Mutation checks: passing the pool instead of arrivals to `_update_access_rate`; skipping consumption; resetting `pending_since` on replacement; letting a protected member go stale; ordering overdue members by score instead of pending time. Each makes a test fail.

## 3. Workspace

- [ ] 3.1 Capacity from `[workspace.pool].capacity` with the pool on; `[workspace].top_k` and the `Workspace` default stay 5.
- [ ] 3.2 Priority for eligible overdue protected members in `_compose`; inhibition unchanged. Tests in `tests/test_workspace_priority.py` for every scenario of the spec, including the bound in broadcasts with eight keys at capacity 1 and 5.
- [ ] 3.3 Novelty once per report: a cache keyed by stream-qualified id in the salience strategy, dropped when the member leaves the pool. Test: five ticks of one held report make one `NoveltyTracker.observe` call.
- [ ] 3.4 `select` takes arrivals separately with the pool on; `observe_candidates` gets arrivals only.
- [ ] 3.5 Consumers keep the threshold rule. Test: with the pool on and no protected member, processors' context, the affect module's concern access and the feedback head read the same accessed set as the threshold rule gives.

## 4. Records

- [ ] 4.1 Research event observer: `pool_size`, `n_accessed`, per-member `held`, `held_s`, `protected`, `pending_s`, `route`; the pool summary; protected access records; defect records; the range sweep bounds the new numeric fields. Tests in the observer test module, including that no payload field appears.
- [ ] 4.2 Ignition log: pool size and per-member `held`, `held_s`, `protected`. Test that no payload field appears.

## 5. Preservation

- [ ] 5.1 Bundles and run manifests record `workspace_supply` and `workspace_capacity`; absence read as `tick` with capacity 5; a revive across a change refuses unless `accept_workspace_change = true`, recorded in the manifest. Tests for the three scenarios.

## 6. Off equals absent, and privacy

- [ ] 6.1 `tests/test_candidate_pool_absent.py`: the deterministic engine run with the pool off reproduces the golden digest of task 0.1 (broadcast payloads, ignition records, research broadcast records, published reports, manifests).
- [ ] 6.2 `tests/test_candidate_pool_privacy.py`: a held `audition.transcription` accessed two broadcasts after arrival is stored by the real episodic memory module as `<heard omitted>`, with no heard text in the store, the database file or the preservation export; the pool's records hold no payload field; boot refuses the pool without the never-persisted bus rule.

## 7. Offline welfare checks (no entity)

- [ ] 7.1 Engine harness: a sustained alert source keeps the access rate inside its pre-change range.
- [ ] 7.2 Adversarial bound harness (gate): the cases of design check 2; every episode closes within the D6 bound in broadcasts and, at nominal pacing, in seconds.
- [ ] 7.3 Real affect and interoception modules on the engine harness (gate): drive episodes accessed before the next re-entry, and alarm-onset-to-access time, no worse under B than under A.
- [ ] 7.4 Real perceptual modules on the real developmental stimulus and the reference programme, on the archived developmental simulation and fixed feed of the band-step and stir harnesses, with the real affect module, under A and B: time to boredom's first crossing, deprivation share, drive trajectories. The ten-point hold rule of the design applies.
- [ ] 7.5 Records of 7.1 to 7.4 under `docs/records/validation/candidate-pool/`, content-free.

## 8. Docs, paper notes and review

- [ ] 8.1 Docs: the workspace and cognitive-cycle chapters (pool, exits, protected types, priority and the wait bound, K = 1, the off switch), `docs/17-research-data/README.md` (record fields). Present tense.
- [ ] 8.2 Paper notes to REVISION-NOTES (proposal's list).
- [ ] 8.3 `openspec validate workspace-continuous-competition --strict` passes.
- [ ] 8.4 Worker first-pass review, then the independent second review (entity dynamics, welfare).
