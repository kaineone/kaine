## Phase 1 — Freeze/Welfare Safety (C1, C2, M3)

- [ ] **C1 — Snapshot/restore desired perception flags.** `kaine/cycle/__main__.py:377-390`: on freeze, capture current desired audio/video state before calling `write_desired_audio/video(False)`; on resume, restore the snapshot. Regression test: `test_freeze_resume_restores_desired_perception` — freeze with desired audio/video true, verify both cleared; resume, verify both restored; repeat freeze/resume cycle.
- [ ] **C2 — Stacked freeze sources; Spot restores, never lifts welfare.** `kaine/cycle/control_state.py:76-87` (replace single-slot overwrite with a stacked, priority-ordered freeze), `kaine/cycle/spot.py:537-539` (Spot stands down for any active freeze, not just operator; on recovery restores the pre-existing freeze stack verbatim), `kaine/cycle/preservation_monitor.py:874-877` and `:704,894` (respect `_acted` latch; never re-liftable except by operator or explicit welfare stand-down). Regression tests: `test_welfare_pause_not_lifted_by_spot_recovery` — welfare freeze + module fault → Spot freezes on top → module recovers → verify freeze remains, reason/source intact, entity NOT resumed; `test_spot_restores_preexisting_freeze_stack`; `test_operator_stand_down_lifts_welfare_freeze` (only path besides welfare stand-down).
- [ ] **M3 — Rate-limit welfare "notify" response.** `kaine/cycle/preservation_monitor.py:894`: apply `min_interval_s` (same mechanism as DivergenceMonitor) to notify fires. Regression test: `test_welfare_notify_rate_limited` — sustained distress over 10× `distress_duration_s` (30 s default) with `min_interval_s` set → bundle count ≤ ceil(duration/min_interval_s), not one per distress cycle.

## Phase 2 — Speech Liveness (C3, H4)

- [ ] **C3 — Realization-failed event + guard timeout.** `kaine/modules/lingua/module.py:375-387`: on generation exception, publish content-free realization-failed event (mode + reason class only; never text or payloads). `kaine/workspace/volition.py:209-217`, `report_policy.py:128-138`, `drive_policy.py:89-103`: clear speak/think in-flight guards on this event; add refractory-scaled timeout on guards as belt-and-suspenders. Regression test: `test_failed_llm_call_unmutes_entity` — raise inside lingua generation → verify event published (assert schema: mode + reason class, no text fields) → verify all three policies clear guards → next cycle speech proceeds; also `test_guard_timeout_clears_without_event`.
- [ ] **H4 — Time-based report-signature expiry.** `kaine/workspace/report_policy.py:106,176,194-198`: add configurable `sig_expiry_s` using the policy's clock; same-signature suppression expires after it elapses. Regression test: `test_same_signature_block_expires` — stable feed with identical (source,type) signature, advance policy clock past `sig_expiry_s`, verify report/speak proceeds.

## Phase 3 — Feeds and Cursors (H1, H2, H3)

- [ ] **H1 — Resync playlist audio to shared clock on producer start.** `kaine/modules/audition/feed.py:432-499`: in `_produce`, on start call `PlaylistClock.locate()` and seek within the current item to its offset (av container seek) or skip decoded frames up to the offset. Regression test: `test_producer_restart_resyncs_to_clock` — run to item N, toggle mute off/restart producer, verify audio resumes at clock position, not item 0; video/audio positions agree within tolerance.
- [ ] **H2 — Poison-proof hot consumers.** `kaine/cycle/engine.py:410,775-783`, `consume_control_events` `:630-631`, `consume_soma_regulation` `:670-671`; `kaine/modules/soma/module.py:517-518`; `kaine/modules/hypnos/module.py:228-229`: switch from `read()` + last-decoded cursor to `read_entries`/`last_scanned` (per `kaine/bus/client.py:192-201` and preservation-monitor precedent). Regression test: `test_poison_batch_does_not_stall_streams` — push a fully-undecodable batch into each affected stream, verify subsequent entries are consumed and cursors advance.
- [ ] **H3 — Seed engine cursors at tail.** `kaine/cycle/engine.py:164,167,186`: at startup, seed all stream cursors to the stream tail (precedent `kaine/modules/hypnos/module.py:186-195`), without a bus wipe. Regression test: `test_restart_does_not_replay_stale_events` — fill streams beyond the failure point with soma reduce_rate advisories and historical control events, restart engine without bus wipe, verify zero replay and rate unchanged.

## Phase 4 — Sleep Robustness (M1, M2, L3)

- [ ] **M1 — Hypnos maintenance poll task.** `kaine/modules/hypnos/module.py`: add a periodic `RestScheduler.is_due()`/`enter_sleep()` poll task inside Hypnos, paced by the subjective clock, fulfilling the `boot.py:1248-1249` promise; no behavior authored beyond invoking the existing scheduler. Regression test: `test_maintenance_runs_without_fatigue_consumer` — shed Soma (fatigue events never fire), advance subjective clock past interval, verify maintenance/enter_sleep occurs.
- [ ] **M2 — Finally-publish sleep completion.** `kaine/modules/hypnos/module.py:340..432`: wrap the pipeline in try/finally guaranteeing `hypnos.sleep.completed` (or publish a sleep-failed event Soma treats identically) so `kaine/modules/soma/module.py:550-565` `_in_hypnos` never wedges. Regression test: `test_transient_publish_failure_does_not_wedge_soma` — make the completed publish fail once, verify Soma exits `_in_hypnos` state (sleep-failed handled identically) and faster_decay stops.
- [ ] **L3 — Sleep task reference + trigger-flag guard.** `kaine/modules/hypnos/module.py:253-256` (hold task reference, no GC), `:267-277,:424` (guard trigger flag against double-trigger mis-annotation of the running sleep's summary). Regression test: `test_sleep_task_not_collected_and_no_double_trigger` — force GC, verify sleep completes; trigger twice, verify the running sleep's summary is not mis-annotated.

## Phase 5 — Engine Hygiene (L1, L2, L4)

- [ ] **L1 — Incremental deterministic logical time.** `kaine/cycle/engine.py:226-230`: accumulate logical time incrementally; no recomputation of past ticks' period on rate change. Regression test: `test_rate_change_does_not_jump_logical_timestamps` — ticks at rate r1, change to r2, verify past tick timestamps unchanged and future ticks increment by 1/r2.
- [ ] **L2 — Clamp experiential accumulator.** `kaine/cycle/engine.py:785-791`: clamp accumulator when throttled below the experiential rate. Regression test: `test_experiential_accumulator_bounded_when_throttled` — throttle below experiential rate for many ticks, verify accumulator ≤ configured bound.
- [ ] **L4 — Log bare excepts in event consumers.** `kaine/cycle/engine.py:626-627,666-667`: log at WARNING with rate limiting. Regression test: `test_persistent_redis_failure_is_visible` — fail the bus for N reads, verify exactly one (rate-limited) WARNING per window in logs.

## Phase 6 — Tests

- [ ] All regression tests above implemented, each named for and keyed to the exact failure scenario in its finding; all pass in deterministic mode.
- [ ] Verify no test introduces raw-sense-data persistence or non-deterministic behavior.

## Phase 7 — Docs

- [ ] Update freeze/welfare semantics docs (stacked sources, operator/welfare-only liftable, C1 snapshot/restore) in present tense.
- [ ] Update consumer guidance: `read_entries`/`last_scanned` for hot consumers, tail-seeded cursors on startup.
- [ ] Document realization-failed event schema (content-free: mode + reason class only) and guard-timeout semantics.
- [ ] Document Hypnos maintenance poll (boot promise at `boot.py:1248-1249`) and welfare notify rate limit; docs in present tense.
- [ ] Confirm zero-raw-sense-data-persistence statement unchanged across all touched docs.
